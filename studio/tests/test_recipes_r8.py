"""Восьмой круг: слой рецептов — допущения инженера по классу работы.

Валидатор седьмого круга: база держит факты вендора по эндпоинтам, но не
допущения, которые применяет опытный инженер, и плановщик читал молчание базы
как нейтральное. Здесь — по рецепту на класс работы и случаи валидатора:
n33 (8K картинка), x15 (60 fps генерация), w23 (царапины), n30 (шумы),
w18 / x20 (логотип), x14 (раскраска до апскейла), w06 (визуализатор), w33
(бюджет 0), n03 (вебкам-запись Анны), x04 (образец голоса), w29 (один ведущий).

Т2: ожидания — литералы; spec — как их написал валидатор по описанию
инструмента. Т4: сети нет; синтетическая база, где состав шагов от живой базы
не зависит (одна проверка источников допущений читает живую базу с диска).
Т1: константы-решения мутируются в `scripts/mutate_recipes.py`.
"""

from __future__ import annotations

import os
import unittest
from datetime import date

import studio.planner as pn
from studio import brief_spec as bs
from studio import l10n
from studio import recipes as rc
from studio.recipes import table as rt
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
    факт("x-t2v", "architecture", "text-to-video model"),
    факт("x-t2v", "price_per_second_usd", "$0.10 per second"),
    факт("x-i2v", "architecture", "image-to-video model"),
    факт("x-i2v", "price_per_second_usd", "$0.10 per second"),
    факт("x-upscale-image", "architecture", "image upscaler (super-resolution) model"),
    факт("x-upscale-image", "price_per_image_usd", "$0.02 per image"),
    факт("x-vsr", "architecture", "video upscaler (super-resolution) model"),
    факт("x-vsr", "price_per_second_usd", "$0.02 per second"),
    факт("x-rife", "architecture", "video frame interpolation model"),
    факт("x-rife", "price_per_second_usd", "$0.01 per second"),
    факт("x-deblur-video", "architecture", "video restoration model: deblur"),
    факт("x-deblur-video", "price_per_second_usd", "$0.01 per second"),
    факт("x-denoise-video", "architecture", "video restoration model: denoise"),
    факт("x-denoise-video", "price_per_second_usd", "$0.02 per second"),
    факт("x-colorize", "architecture", "video colorization model"),
    факт("x-colorize", "price_unit_megapixel_usd", "$0.002 per megapixel"),
    факт("x-sfx", "architecture", "text-to-sound-effects model"),
    факт("x-sfx", "price_per_second_usd", "$0.002 per second"),
    факт("x-sfx", "requires_inputs", "текст"),
    факт("x-foley", "architecture", "sound effects model (video-to-audio)"),
    факт("x-foley", "price_per_second_usd", "$0.003 per second"),
    факт("x-foley", "requires_inputs", "видео, текст"),
    факт("x-voice-clone", "architecture", "voice cloning text-to-speech model"),
    факт("x-voice-clone", "price_per_minute_usd", "$0.10 per minute"),
    факт("x-tts", "architecture", "text-to-speech model"),
    факт("x-tts", "price_per_minute_usd", "$0.10 per minute"),
    факт("x-lips", "architecture", "lipsync model"),
    факт("x-lips", "price_per_second_usd", "$0.05 per second"),
    факт("x-avatar", "architecture", "talking avatar model (audio-driven portrait)"),
    факт("x-avatar", "price_per_second_usd", "$0.10 per second"),
    факт("x-avatar", "requires_inputs", "изображение, аудио"),
)


def план(spec: dict, база: tuple[Fact, ...] = БАЗА, бриф: str = "spec-only call") -> dict:
    return pn.plan(бриф, facts=list(база), today=СЕГОДНЯ, full=True, spec=spec, spec_only=True)


def шаги(п: dict) -> list[tuple[str, str | None]]:
    return [(ш["step"], (ш.get("chosen") or {}).get("model")) for ш in п["steps"]]


def допущения(п: dict) -> list[str]:
    return [д["id"] for д in (п.get("recipe") or {}).get("priors_applied", [])]


def выключены(п: dict) -> list[str]:
    return list((п.get("recipe") or {}).get("priors_overridden", []))


def V(sec: float | None = None, **k) -> dict:
    return {"kind": "video", "owned": True, **({"duration_s": sec} if sec else {}), **k}


def I() -> dict:
    return {"kind": "image", "owned": True}


def A(sec: float) -> dict:
    return {"kind": "audio", "owned": True, "duration_s": sec}


T = {"kind": "text", "owned": True}


class Таблица(unittest.TestCase):
    """Таблица рецептов цельна: ссылки сходятся, у каждого допущения тег, источники живы."""

    def test_теги_и_источники(self) -> None:
        for п in rt.PRIORS_LIST:
            self.assertIn(п.tag, (rt.TAG_ENGINEERING, rt.TAG_BASE_ROWS), п.id)
            # Допущение по строкам базы без строк — не допущение по строкам.
            self.assertEqual(п.tag == rt.TAG_BASE_ROWS, bool(п.sources), п.id)
            self.assertTrue(п.en and п.ru, п.id)

    def test_источники_есть_в_живой_базе(self) -> None:
        живые = {(f.model, f.attribute, f.source_url) for f in pn.FactIndex().facts}
        for п in rt.PRIORS_LIST:
            for и in п.sources:
                self.assertIn((и.model, и.attribute, и.url), живые, (п.id, и))

    def test_ссылки_рецептов(self) -> None:
        имена_оп = {оп.name for оп in pn.OPERATIONS}
        for р in rt.RECIPES_LIST:
            for п in р.priors:
                self.assertIn(п, rt.PRIORS, р.id)
            for ш in р.steps:
                self.assertIn(ш.kind, ("model", "tool"))
                if ш.kind == "model":
                    self.assertIn(ш.what, имена_оп, р.id)
            # Инструменты и проверки рецепта — ровно то, что приносят его допущения
            # (оверлей логотипа добавляет xfade для анимированной заставки).
            from_priors = {т for п in р.priors for т in rt.PRIORS[п].tools}
            self.assertEqual(set(р.tools) - {"ffmpeg_xfade"}, from_priors, р.id)
            self.assertEqual(set(р.failures), {ф for п in р.priors for ф in rt.PRIORS[п].failures}, р.id)
            for т in р.tools:
                self.assertIn(т, rt.TOOLS)
        for п in rt.PRIORS_LIST:
            for т in п.tools:
                self.assertIn(т, rt.TOOLS, п.id)
            for ф in п.failures:
                self.assertIn(ф, rt.FAILURES, п.id)
            self.assertEqual(1, sum(п.id in р.priors for р in rt.RECIPES_LIST), п.id)


class Порядок(unittest.TestCase):
    def test_реставрация_раскраска_апскейл_интерполяция(self) -> None:
        self.assertEqual(
            ["реставрация", "раскраска", "апскейл", "интерполяция_кадров"],
            rc.order(["апскейл", "интерполяция_кадров", "раскраска", "реставрация"]),
        )

    def test_прочие_шаги_на_своих_местах(self) -> None:
        self.assertEqual(
            ["клонирование_голоса", "генерация_видео", "раскраска", "музыка", "апскейл"],
            rc.order(["генерация_видео", "апскейл", "музыка", "раскраска", "клонирование_голоса"]),
        )


class ПределыКлассаНаМолчании(unittest.TestCase):
    """n33 и x15: молчание базы о модели — не нейтрально, когда у класса есть предел."""

    N33 = {"task": "generate", "inputs": [], "outputs": ["image"], "shots": 1, "resolution": "7680x4320", "people": []}
    X15 = {
        "task": "generate",
        "inputs": [],
        "outputs": ["video"],
        "duration_s": 8,
        "resolution": "1080p",
        "fps": 60,
        "aspect": "16:9",
        "people": [],
    }

    def test_n33_8k_картинка_апскейл_последним(self) -> None:
        п = план(self.N33)
        self.assertEqual([("генерация_изображения", "x-t2i"), ("апскейл_изображения", "x-upscale-image")], шаги(п))
        self.assertEqual(["t2i_native_max"], допущения(п))
        self.assertEqual(["still_image"], п["recipe"]["classes"])
        self.assertTrue(п["steps"][1]["inferred"].startswith("prior t2i_native_max (class prior from base rows)"))
        self.assertIn(
            "prior t2i_native_max (class prior from base rows): text-to-image models render natively up to about "
            "2K-4K (4096x4096 at most)",
            " | ".join(п["understood_as"]["assumptions"]),
        )
        self.assertEqual("", п["resolution_carry"])

    def test_n33_выключено_spec(self) -> None:
        п = план({**self.N33, "priors": {"t2i_native_max": False}})
        self.assertEqual([("генерация_изображения", "x-t2i")], шаги(п))
        self.assertEqual(([], ["t2i_native_max"]), (допущения(п), выключены(п)))
        self.assertIn("no upscale step added", п["resolution_carry"])

    def test_4k_картинка_без_апскейла(self) -> None:
        п = план({**self.N33, "resolution": "3840x2160"})
        self.assertEqual([("генерация_изображения", "x-t2i")], шаги(п))
        self.assertIsNone(п["recipe"])

    def test_записанный_факт_старше_допущения(self) -> None:
        база = (*БАЗА, факт("x-t2i", "max_resolution", "up to 8192x8192"))
        п = план(self.N33, база)
        self.assertEqual([("генерация_изображения", "x-t2i")], шаги(п))
        self.assertIsNone(п["recipe"])

    def test_8k_видео_апскейл_4k_нет(self) -> None:
        spec = {"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 6, "resolution": "8k", "people": []}
        п = план(spec)
        self.assertEqual([("генерация_видео", "x-t2v"), ("апскейл", "x-vsr")], шаги(п))
        self.assertEqual(["t2v_native_max"], допущения(п))
        п = план({**spec, "resolution": "4k"})
        self.assertEqual([("генерация_видео", "x-t2v")], шаги(п))
        self.assertIsNone(п["recipe"])

    def test_x15_60_fps_интерполяция(self) -> None:
        п = план(self.X15)
        self.assertEqual([("генерация_видео", "x-t2v"), ("интерполяция_кадров", "x-rife")], шаги(п))
        self.assertEqual(["t2v_fps_native"], допущения(п))
        self.assertEqual("", п["frame_rate"]["note"])
        источники = [и["model"] for и in п["recipe"]["priors_applied"][0]["sources"]]
        self.assertEqual(["kling-3.0", "wan-2.2-t2v-a14b", "minimax-h3", "wan-2.7-i2v"], источники)

    def test_x15_выключено_и_30_fps(self) -> None:
        п = план({**self.X15, "priors": {"t2v_fps_native": False}})
        self.assertEqual([("генерация_видео", "x-t2v")], шаги(п))
        self.assertEqual(["t2v_fps_native"], выключены(п))
        self.assertIn("not added on silence", п["frame_rate"]["note"])
        п = план({**self.X15, "fps": 30})
        self.assertEqual([("генерация_видео", "x-t2v")], шаги(п))
        self.assertIsNone(п["recipe"])

    def test_x15_записанные_60_fps_старше(self) -> None:
        п = план(self.X15, (*БАЗА, факт("x-t2v", "fps", "24 / 30 / 60 fps")))
        self.assertEqual([("генерация_видео", "x-t2v")], шаги(п))
        self.assertIsNone(п["recipe"])


class СвоёУЗаказчика(unittest.TestCase):
    """n03, x04, w29: то, что заказчик принёс, — в дело; один ведущий — один референс."""

    def test_n03_вебкам_анны_липсинк_и_клон(self) -> None:
        spec = {
            "task": "avatar",
            "inputs": [V(120)],
            "outputs": ["video", "speech"],
            "duration_s": 60,
            "resolution": "1080p",
            "languages": ["de"],
            "people": [{"name": "Anna (colleague)", "real": True, "public_figure": False, "consent": "stated", "claim": "none"}],
        }
        п = план(spec)
        self.assertEqual([("клонирование_голоса", "x-voice-clone"), ("липсинк", "x-lips")], шаги(п))
        self.assertEqual(["own_video_likeness"], допущения(п))
        self.assertIn("the voice sample is taken out of YOUR video (ffmpeg -vn) — 0 usd", п["assembly"]["why"])
        выкл = план({**spec, "priors": {"own_video_likeness": False}})
        self.assertEqual(
            [("генерация_изображения", "x-t2i"), ("озвучка", "x-tts"), ("говорящий_аватар", "x-avatar")], шаги(выкл)
        )

    def test_x04_образец_голоса_клонируется(self) -> None:
        spec = {
            "task": "avatar",
            "inputs": [I(), A(60), T],
            "outputs": ["video", "speech"],
            "duration_s": 20,
            "languages": ["es"],
            "people": [{"name": "abuela", "real": True, "public_figure": False, "consent": "stated", "claim": "none"}],
        }
        п = план(spec)
        self.assertEqual([("клонирование_голоса", "x-voice-clone"), ("говорящий_аватар", "x-avatar")], шаги(п))
        self.assertEqual(["voice_sample_clone"], допущения(п))
        self.assertEqual(["voice clone + narration", "talking avatar (photo + voice)"], [о["label"] for о in п["recipe"]["order"]])
        выкл = план({**spec, "priors": {"voice_sample_clone": False}})
        self.assertEqual([("говорящий_аватар", "x-avatar")], шаги(выкл))

    def test_запись_без_текста_это_дорожка(self) -> None:
        п = план({"task": "avatar", "inputs": [I(), A(20)], "outputs": ["video"], "duration_s": 20, "people": []})
        self.assertEqual([("говорящий_аватар", "x-avatar")], шаги(п))
        self.assertIsNone(п["recipe"])

    W29 = {
        "task": "avatar",
        "inputs": [],
        "outputs": ["video", "speech"],
        "shots": 5,
        "per_shot_s": 20,
        "characters": 1,
        "languages": ["en"],
        "aspect": "9:16",
        "budget": {"amount": 25, "currency": "USD"},
        "people": [],
    }

    def _картинок(self, п: dict) -> str:
        смета = {ш["step"]: ш for ш in п["pipeline_price"]["смета"]["steps"]}
        return смета["генерация_изображения"]["formula"]

    def test_w29_один_референс_на_пять_роликов(self) -> None:
        п = план(self.W29)
        self.assertEqual(
            [("генерация_изображения", "x-t2i"), ("озвучка", "x-tts"), ("говорящий_аватар", "x-avatar")], шаги(п)
        )
        self.assertEqual(["single_reference"], допущения(п))
        self.assertTrue(self._картинок(п).startswith("1 image(s)"), self._картинок(п))
        выкл = план({**self.W29, "priors": {"single_reference": False}})
        self.assertTrue(self._картинок(выкл).startswith("5 image(s)"), self._картинок(выкл))

    def test_один_ролик_не_серия(self) -> None:
        п = план({**self.W29, "shots": 1})
        self.assertIsNone(п["recipe"])


class Логотип(unittest.TestCase):
    """w18 и x20: логотип — из файла заказчика при сборке, не сгенерированные буквы."""

    W18 = {"task": "animate", "inputs": [I()], "outputs": ["video"], "duration_s": 4, "resolution": "4k", "conditions": ["logo legible"], "people": []}
    X20 = {
        "task": "generate",
        "inputs": [I()],
        "outputs": ["video"],
        "duration_s": 15,
        "aspect": "16:9",
        "conditions": ["logo legible", "text legible"],
        "people": [],
    }

    def test_w18_заставка_перетекает_в_настоящий_логотип(self) -> None:
        п = план(self.W18)
        self.assertEqual([("оживление", "x-i2v")], шаги(п))
        self.assertEqual(["logo_overlay"], допущения(п))
        self.assertIn(
            "final hold: the generated motion crossfades (ffmpeg xfade) into the true logo from YOUR file — 0 usd",
            п["assembly"]["why"],
        )
        self.assertEqual(["ffmpeg overlay", "ffmpeg xfade"], [т["name"] for т in п["recipe"]["tools"]])

    def test_x20_реклама_без_текста_и_финальная_карточка(self) -> None:
        п = план(self.X20)
        self.assertEqual([("генерация_видео", "x-t2v")], шаги(п))
        self.assertEqual(["logo_image_is_endcard", "logo_overlay"], допущения(п))
        self.assertEqual(
            [
                "the logo is composited from YOUR file (ffmpeg overlay) as the end card — letter for letter; no "
                "generated lettering is used — 0 usd"
            ],
            п["assembly"]["why"],
        )
        выкл = план({**self.X20, "priors": {"logo_image_is_endcard": False, "logo_overlay": False}})
        self.assertEqual([("оживление", "x-i2v")], шаги(выкл))
        self.assertEqual(["logo_image_is_endcard", "logo_overlay"], выключены(выкл))
        self.assertIsNone(выкл["assembly"])


class Шумы(unittest.TestCase):
    N30 = {"task": "generate", "inputs": [V(30)], "outputs": ["sfx"], "duration_s": 30, "people": []}

    def test_n30_видео_в_звук(self) -> None:
        п = план(self.N30)
        self.assertEqual([("звук_фон", "x-foley")], шаги(п))
        self.assertEqual(["foley_v2a"], допущения(п))
        self.assertNotIn("prior_not_met", п["recipe"])
        выкл = план({**self.N30, "priors": {"foley_v2a": False}})
        self.assertEqual([("звук_фон", "x-sfx")], шаги(выкл))

    def test_n30_нет_модели_видео_в_звук_говорится(self) -> None:
        база = tuple(f for f in БАЗА if f.model != "x-foley")
        п = план(self.N30, база)
        self.assertEqual([("звук_фон", "x-sfx")], шаги(п))
        строка = п["recipe"]["prior_not_met"][0]
        self.assertEqual(("звук_фон", "x-sfx", "fail"), (строка["step"], строка["model"], строка["outcome"]))


class Плёнка(unittest.TestCase):
    W23 = {"task": "restore", "inputs": [V(300)], "outputs": ["video"], "duration_s": 300, "resolution": "1080p", "people": []}
    X14 = {"task": ["restore", "colorize", "upscale"], "inputs": [V(600)], "outputs": ["video"], "duration_s": 600, "resolution": "4k", "people": []}

    def test_w23_царапины_не_деблюр(self) -> None:
        п = план(self.W23)
        self.assertEqual([("реставрация", "x-denoise-video")], шаги(п))
        self.assertEqual(["film_damage_not_blur"], допущения(п))
        self.assertEqual(["ffmpeg deflicker", "VapourSynth DeScratch / RemoveDirt"], [т["name"] for т in п["recipe"]["tools"]])
        выкл = план({**self.W23, "priors": {"film_damage_not_blur": False}})
        self.assertEqual([("реставрация", "x-deblur-video")], шаги(выкл))

    def test_размытие_названо_деблюр_можно(self) -> None:
        п = план({**self.W23, "conditions": ["motion blur"]})
        self.assertEqual([("реставрация", "x-deblur-video")], шаги(п))

    def test_x14_раскраска_до_апскейла_в_кадре_исходника(self) -> None:
        п = план(self.X14)
        self.assertEqual(
            [("реставрация", "x-denoise-video"), ("раскраска", "x-colorize"), ("апскейл", "x-vsr")], шаги(п)
        )
        self.assertEqual(["film_damage_not_blur", "restore_colourise_upscale_order"], допущения(п))
        смета = {ш["step"]: ш for ш in п["pipeline_price"]["смета"]["steps"]}
        # Исходник без кадра — кадр-допущение 1080p (2.0736 Мп), а не 4K (8.2944 Мп).
        self.assertTrue(смета["раскраска"]["formula"].startswith("2.0736 MP/frame"), смета["раскраска"]["formula"])
        self.assertIn("раскраска", pn.SOURCE_EDIT_STEPS)

    def test_x14_порядок_и_при_другом_порядке_в_spec(self) -> None:
        п = план({**self.X14, "task": ["restore", "upscale", "colorize"]})
        self.assertEqual(["реставрация", "раскраска", "апскейл"], [ш for ш, _ in шаги(п)])


class Визуализатор(unittest.TestCase):
    W06 = {"task": "music-visualiser", "inputs": [A(240)], "outputs": ["video"], "duration_s": 240, "resolution": "1080p", "aspect": "16:9", "people": []}

    def test_w06_короткие_петли_а_не_240_с_t2v(self) -> None:
        п = план(self.W06)
        self.assertEqual([("генерация_видео", "x-t2v")], шаги(п))
        self.assertEqual(["visualiser_loops"], допущения(п))
        self.assertEqual(3.2, п["pipeline_price"]["за_ролик"]["usd"])
        self.assertIn(
            "the 4 clips of 8 s are looped and cut on the track's beats (ffmpeg concat) to its full length — 0 usd",
            п["assembly"]["why"],
        )
        выкл = план({**self.W06, "priors": {"visualiser_loops": False}})
        self.assertEqual(24.0, выкл["pipeline_price"]["за_ролик"]["usd"])


class БюджетНоль(unittest.TestCase):
    def test_w33_бесплатный_путь_назван(self) -> None:
        база = (*БАЗА, факт("x-t2i", "weights_url", "https://huggingface.co/x/x-t2i (Apache-2.0)"))
        п = план({"task": "generate", "inputs": [], "outputs": ["image"], "shots": 1, "budget": {"amount": 0, "currency": "USD"}, "people": []}, база)
        self.assertEqual(["zero_budget_self_host"], допущения(п))
        путь = п["recipe"]["free_route"]
        self.assertEqual("генерация_изображения", путь["open_weights"][0]["step"])
        self.assertTrue(путь["note"].startswith("0 usd per call on your own or a free GPU"))


class Язык(unittest.TestCase):
    def test_русский_ответ_без_английских_оборотов(self) -> None:
        п = pn.plan(
            "Нужно 5 shorts по 20 sec каждый, один и тот же talking host",
            facts=list(БАЗА),
            today=СЕГОДНЯ,
            full=True,
            spec=СвоёУЗаказчика.W29,
            spec_only=True,
        )
        self.assertEqual("инженерное допущение", п["recipe"]["priors_applied"][0]["tag"])
        self.assertEqual([], l10n.leaks(l10n.localise_payload(п["recipe"], "ru"), "ru"))
        self.assertEqual([], l10n.leaks(l10n.localise_payload(п["understood_as"]["assumptions"], "ru"), "ru"))

    def test_английский_ответ_без_кириллицы(self) -> None:
        for spec in (Плёнка.X14, Логотип.X20, Шумы.N30, Визуализатор.W06):
            п = план(spec)
            self.assertEqual([], l10n.leaks(l10n.localise_payload(п["recipe"], "en"), "en"), spec)


class ПлохойSpec(unittest.TestCase):
    def test_неизвестное_допущение_ошибка(self) -> None:
        _, ошибки = bs.parse_spec({"priors": {"t2v_fps": False, "foley_v2a": "no"}})
        self.assertEqual(2, len(ошибки))
        self.assertTrue(ошибки[0].startswith("spec.priors.t2v_fps: unknown prior (known: t2i_native_max,"), ошибки)
        self.assertEqual("spec.priors.foley_v2a='no': must be true or false", ошибки[1])


if __name__ == "__main__":
    os.environ.setdefault("STUDIO_NO_JOURNAL", "1")
    unittest.main()
