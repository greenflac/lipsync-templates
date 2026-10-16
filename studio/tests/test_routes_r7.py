"""Седьмой круг: словарь spec и таблица маршрутов как модель пространства работ.

Валидатор седьмого круга (вызывающая модель, читавшая только описание
инструмента) дошёл до плана в 66 из 70 брифов, но верным по ремеслу план был
в ~45. Корень — словарь spec и маршруты: нарезка шортсов звала генеративную
правку ($179) при пометке «ничего не генерируется»; каждый дубляж получал
липсинк; раскраски не было; стабилизация уходила в генеративную правку;
язык жестов собирался говорящим аватаром; 120 fps отдавались моделью с 24 fps;
серия картинок с одним персонажем — N независимых генераций; бюджет 0
печатал `pass`; японский бриф с полной spec получал «бриф пуст».

Т2: ожидания — литералы; spec — такие, какими их заполняет вызывающий по
описанию инструмента. Т4: сети нет; план собирается на синтетической базе, где
состав шагов от базы не зависит. Т1: константы-решения мутируются в
`scripts/mutate_brief_spec.py`.
"""

from __future__ import annotations

import json
import os
import unittest
from datetime import date

import studio.planner as pn
from studio import brief_spec as bs
from studio import pricing
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
    факт("x-t2v", "fps", "24"),
    факт("x-asr", "architecture", "speech-to-text transcription model with timestamps"),
    факт("x-asr", "price_per_minute_usd", "$0.01 per minute"),
    факт("x-vsr", "architecture", "video upscaler (super-resolution) model"),
    факт("x-vsr", "price_per_second_usd", "$0.02 per second"),
)


def план(spec: dict, бриф: str = "spec-only call") -> dict:
    return pn.plan(бриф, facts=list(БАЗА), today=СЕГОДНЯ, full=True, spec=spec, spec_only=True)


def шаги(итог: dict) -> list[str]:
    return [ш["step"] for ш in итог["steps"]]


def свой(kind: str, сек: float | None = None, **ещё: object) -> dict:
    return {"kind": kind, "owned": True, **({"duration_s": сек} if сек else {}), **ещё}


def маршрут(raw: dict, на_сборке: frozenset[str] | None = None) -> bs.Маршрут:
    spec, ошибки = bs.parse_spec(raw)
    assert not ошибки, ошибки
    return bs.route(spec, на_сборке)


# --- 2. Нарезка: монтаж, а не генеративная правка ----------------------------------


class НарезкаМонтажом(unittest.TestCase):
    def test_шортсы_одна_расшифровка_и_монтаж(self) -> None:
        м = маршрут({"task": "cut-to-shorts", "inputs": [свой("video", 4500)], "outputs": ["video"], "shots": 8, "per_shot_s": 40})
        self.assertEqual(("расшифровка",), м.шаги)
        self.assertEqual((bs.NOTE_SHORTS_EDIT,), м.сборка)

    def test_шортсы_с_субтитрами_вжигаются_монтажом(self) -> None:
        м = маршрут(
            {"task": ["cut-to-shorts", "captions"], "inputs": [свой("video", 4500)], "outputs": ["video"],
             "shots": 8, "per_shot_s": 40, "languages": ["en"]}
        )
        self.assertEqual(("расшифровка",), м.шаги)
        self.assertEqual((bs.NOTE_SHORTS_EDIT, bs.NOTE_CAPTIONS), м.сборка)

    def test_одна_нарезка_по_duration_s_без_шортсов(self) -> None:
        """w01: «3-минутный хайлайт из двух часов» — третий вызов был лишним."""
        _, ошибки, нет = bs.gaps(
            {"task": "cut-to-shorts", "inputs": [свой("video", 7200)], "outputs": ["video", "music"], "duration_s": 180}
        )
        self.assertEqual(([], []), (ошибки, нет))
        _, _, нет = bs.gaps({"task": "cut-to-shorts", "inputs": [свой("video", 7200)], "outputs": ["video"]})
        self.assertEqual(["shots", "per_shot_s"], [н["field"] for н in нет])

    def test_хайлайт_цена_плана_годна_без_шага_ролика(self) -> None:
        итог = план(
            {"task": "cut-to-shorts", "inputs": [свой("video", 7200)], "outputs": ["video"], "duration_s": 180}
        )
        self.assertEqual(["расшифровка"], шаги(итог))
        self.assertNotIn("no_clip_price", итог["pipeline_price"])
        self.assertEqual(0.0, итог["pipeline_price"].get("over_ceiling", {}).get("least_known_usd", 0.0))
        self.assertTrue(any("ffmpeg — 0 usd" in п for п in итог["assembly"]["why"]), итог["assembly"])


# --- 3. spec.edit описан и виден -------------------------------------------------------


class ПравкаОписана(unittest.TestCase):
    def test_allowed_называет_все_правки(self) -> None:
        self.assertTrue(
            bs.OPTIONAL_HELP["edit"].startswith(
                "for video-edit — WHAT is edited: a list of reframe | replace-object | remove-object | "
                "replace-sky | stabilise | relight | day-to-night | restyle"
            )
        )

    def test_описание_инструмента_называет_правки(self) -> None:
        from studio.mcp import server

        док = " ".join((server.plan_pipeline.__doc__ or "").split())
        self.assertIn(
            "edit for video-edit: [reframe | replace-object | remove-object | replace-sky | stabilise | relight | restyle]",
            док,
        )
        self.assertIn("lipsync for dub-translate: true | false.", док)
        self.assertIn("cut-to-shorts | colorize", док)

    def test_черновик_читает_правку(self) -> None:
        self.assertEqual(
            ["remove-object"],
            bs.draft("Remove a passer-by who walks through the background of our 12 s product shot, 4K")["spec"]["edit"],
        )
        self.assertEqual(["stabilise"], bs.draft("Stabilise my shaky 45 s handheld walking vlog")["spec"]["edit"])


# --- 4. Дубляж: губы только когда их просят ---------------------------------------


class ДубляжИГубы(unittest.TestCase):
    def test_закадровый_дубляж_без_липсинка(self) -> None:
        """n16: «no lipsync needed, voice-over is fine»."""
        м = маршрут(
            {"task": "dub-translate", "inputs": [свой("video", 120)], "outputs": ["speech"], "audio": "voiceover",
             "languages": ["hi", "ta", "bn"]}
        )
        self.assertEqual((("дубляж",), {"дубляж": bs.NOTE_DUB_AUDIO}), (м.шаги, dict(м.пометки)))

    def test_видео_на_выходе_губы_по_умолчанию(self) -> None:
        м = маршрут({"task": "dub-translate", "inputs": [свой("video", 90)], "outputs": ["video", "speech"], "languages": ["pl"]})
        self.assertEqual(("дубляж", "липсинк"), м.шаги)

    def test_lipsync_false_дорожка_в_ролик_монтажом(self) -> None:
        м = маршрут(
            {"task": "dub-translate", "inputs": [свой("video", 90)], "outputs": ["video", "speech"], "languages": ["pl"],
             "lipsync": False}
        )
        self.assertEqual((("дубляж",), (bs.NOTE_DUB_MUX,)), (м.шаги, м.сборка))

    def test_lipsync_true_и_при_закадровом(self) -> None:
        м = маршрут(
            {"task": "dub-translate", "inputs": [свой("video", 90)], "outputs": ["speech"], "audio": "voiceover",
             "languages": ["pl"], "lipsync": True}
        )
        self.assertEqual(("дубляж", "липсинк"), м.шаги)

    def test_lipsync_не_булево_ошибка(self) -> None:
        _, ошибки = bs.parse_spec({"lipsync": "yes"})
        self.assertEqual(["spec.lipsync='yes': must be true or false"], ошибки)

    def test_пример_без_выдуманного_условия(self) -> None:
        """п.10: «profile face» в примере, бриф которого о профиле молчит."""
        from studio.mcp import server

        self.assertNotIn("conditions", bs.EXAMPLE_SPEC)
        self.assertTrue(bs.EXAMPLE_SPEC["lipsync"])
        self.assertNotIn('"conditions": ["profile face"]', server.plan_pipeline.__doc__ or "")


# --- 5. Раскраска — своя работа ----------------------------------------------------


class Раскраска(unittest.TestCase):
    def test_раскраска_своим_шагом(self) -> None:
        self.assertEqual(("раскраска",), маршрут({"task": "colorize", "inputs": [свой("video", 180)], "outputs": ["video"]}).шаги)
        self.assertEqual("colorize", pn.ФУНКЦИЯ_ОПЕРАЦИИ["раскраска"])

    def test_реставрация_и_раскраска_два_шага(self) -> None:
        м = маршрут({"task": ["restore", "colorize"], "inputs": [свой("video", 180)], "outputs": ["video"]})
        self.assertEqual(("реставрация", "раскраска"), м.шаги)

    def test_черновик_раскраски(self) -> None:
        self.assertEqual("colorize", bs.draft("Colorize a 3-minute 1940s black-and-white family film, 1080p")["spec"]["task"])
        self.assertEqual(["restore", "colorize"], bs.draft("Restore and colorize our 1950s 8mm film")["spec"]["task"])
        self.assertEqual(
            "restore", bs.draft("Restore a scratched 1970s 8mm home movie, keep it black and white")["spec"]["task"]
        )


# --- 6. Не генеративное и не поддерживаемое ------------------------------------------


class МонтажИПробелы(unittest.TestCase):
    def test_стабилизация_монтажом_когда_эндпоинта_нет(self) -> None:
        м = маршрут({"task": "video-edit", "inputs": [свой("video", 45)], "outputs": ["video"], "edit": ["stabilise"]})
        self.assertEqual(((), (bs.NOTE_STABILISE,), ()), (м.шаги, м.сборка, м.правки))

    def test_стабилизация_моделью_когда_эндпоинт_есть(self) -> None:
        м = маршрут(
            {"task": "video-edit", "inputs": [свой("video", 45)], "outputs": ["video"], "edit": ["stabilise"]},
            на_сборке=frozenset(),
        )
        self.assertEqual((("правка_видео",), (), None), (м.шаги, м.сборка, м.правки))

    def test_стабилизация_и_удаление_объекта(self) -> None:
        м = маршрут(
            {"task": "video-edit", "inputs": [свой("video", 45)], "outputs": ["video"], "edit": ["stabilise", "remove-object"]}
        )
        self.assertEqual((("правка_видео",), (bs.NOTE_STABILISE,), ("remove-object",)), (м.шаги, м.сборка, м.правки))

    def test_стабилизация_план_без_модели(self) -> None:
        итог = план({"task": "video-edit", "inputs": [свой("video", 45)], "outputs": ["video"], "edit": ["stabilise"]})
        self.assertEqual(
            ([], "could not measure", "только_монтаж", 0.0),
            (итог["steps"], итог["outcome"], итог["reason"], итог["pipeline_price"]["смета"]["usd"]),
        )

    def test_реестр_без_стабилизации_отдаёт_её_монтажу(self) -> None:
        self.assertEqual(frozenset({"stabilise"}), pn.правки_на_сборке(pn.FactIndex(facts=list(БАЗА))))

    def test_язык_жестов_пробел_а_не_аватар(self) -> None:
        """w10: «Sign-language avatar … in ASL» собирался говорящим аватаром."""
        for raw in (
            {"task": "avatar", "inputs": [{"kind": "text", "owned": True}], "outputs": ["video"], "languages": ["ase"]},
            {"task": "avatar", "inputs": [], "outputs": ["video"], "languages": ["en"], "conditions": ["ASL sign language"]},
            {"task": "avatar", "inputs": [], "outputs": ["video"], "languages": ["en"], "conditions": ["sign language interpreter"]},
        ):
            self.assertEqual((bs.NOTE_SIGN, bs.NOTES_EN[bs.NOTE_SIGN]), маршрут(raw).пробел, raw)
        self.assertIsNone(
            маршрут({"task": "avatar", "inputs": [], "outputs": ["video"], "languages": ["en"]}).пробел
        )

    def test_язык_жестов_план(self) -> None:
        итог = план(
            {"task": "avatar", "inputs": [{"kind": "text", "owned": True}], "outputs": ["video"], "duration_s": 60,
             "languages": ["ase"]},
            бриф="Sign-language avatar that signs our 1-minute announcement in ASL",
        )
        self.assertEqual(
            ([], "could not measure", "работа_не_поддерживается", "sign-language"),
            (итог["steps"], итог["outcome"], итог["reason"], итог["gap"]["job"]),
        )
        self.assertTrue(итог["summary"].startswith("NOT SUPPORTED: sign language is not something generative models do"))

    def test_язык_жестов_словами_брифа_при_spec_без_тега(self) -> None:
        """Вызывающий поставил languages=["en"], а бриф говорит «ASL» — аватара всё равно нет."""
        итог = план(
            {"task": "avatar", "inputs": [{"kind": "text", "owned": True}], "outputs": ["video"], "duration_s": 60,
             "languages": ["en"]},
            бриф="Sign-language avatar that signs our 1-minute announcement in ASL",
        )
        self.assertEqual(([], "работа_не_поддерживается"), (итог["steps"], итог["reason"]))

    def test_визуализатор_реагирует_на_звук_при_сборке(self) -> None:
        м = маршрут({"task": "music-visualiser", "inputs": [свой("audio", 240)], "outputs": ["video"]})
        self.assertEqual((("генерация_видео",), (bs.NOTE_VISUALISER, bs.NOTE_VISUALISER_SYNC)), (м.шаги, м.сборка))
        self.assertIn(
            "generated t2v footage does NOT hear the track and is not audio-reactive",
            bs.ASSEMBLY_REASONS[bs.NOTE_VISUALISER_SYNC][1],
        )


# --- 7. Частота кадров ---------------------------------------------------------------


class ЧастотаКадров(unittest.TestCase):
    def test_частоты_из_строк(self) -> None:
        self.assertEqual(["24"], pn._частоты_строки("24 fps (measured; contradicts the 30/60 fps in blogs)"))
        self.assertEqual(["30"], pn._частоты_строки("30fps fixed, 720P or 1080P, 2 to 15 whole seconds"))
        self.assertEqual(["25", "50"], pn._частоты_строки("25 or 50 (fal enum)"))
        self.assertEqual(24.0, pn.частота_записана("x-t2v", list(БАЗА)))
        self.assertIsNone(pn.частота_записана("x-t2i", list(БАЗА)))

    def test_выше_записанной_шаг_интерполяции(self) -> None:
        """n08: 120 fps у модели с записанными 24 fps."""
        итог = план({"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 5, "fps": 120})
        self.assertEqual(["генерация_видео", "интерполяция_кадров"], шаги(итог))
        self.assertEqual(
            "120 fps asked, and x-t2v (video from scratch) records 24 fps at most — frame interpolation "
            "(RIFE / FILM / AMT) lifts it",
            итог["steps"][1]["inferred"],
        )

    def test_не_выше_записанной_шага_нет(self) -> None:
        итог = план({"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 5, "fps": 24})
        self.assertEqual(["генерация_видео"], шаги(итог))
        self.assertEqual({"asked": 24.0, "note": ""}, итог["frame_rate"])

    def test_своё_видео_без_частоты_нота(self) -> None:
        итог = план({"task": "upscale", "inputs": [свой("video", 30)], "outputs": ["video"], "resolution": "4k", "fps": 60})
        self.assertNotIn("интерполяция_кадров", шаги(итог))
        self.assertEqual(
            "60 fps asked: the frame rate of YOUR video is not stated and the base records none for x-vsr — if the "
            "source is below 60 fps, add frame interpolation (RIFE / FILM)",
            итог["frame_rate"]["note"],
        )


# --- 8. Серия картинок с одним персонажем ------------------------------------------


class СерияСПерсонажем(unittest.TestCase):
    def test_референс_и_правки(self) -> None:
        """w02: 24 иллюстрации с тем же ёжиком."""
        м = маршрут({"task": "generate", "inputs": [], "outputs": ["image"], "shots": 24, "characters": 1})
        self.assertEqual(("генерация_изображения", "редактирование_изображения"), м.шаги)
        self.assertEqual({"генерация_изображения": 1, "редактирование_изображения": 24}, dict(м.штук))

    def test_без_персонажа_и_одна_картинка_генерация(self) -> None:
        self.assertEqual(("генерация_изображения",), маршрут({"task": "generate", "inputs": [], "outputs": ["image"], "shots": 24}).шаги)
        self.assertEqual(
            ("генерация_изображения",),
            маршрут({"task": "generate", "inputs": [], "outputs": ["image"], "shots": 1, "characters": 1}).шаги,
        )

    def test_две_картинки_уже_серия(self) -> None:
        м = маршрут({"task": "generate", "inputs": [], "outputs": ["image"], "shots": 2, "characters": 1})
        self.assertEqual({"генерация_изображения": 1, "редактирование_изображения": 2}, dict(м.штук))

    def test_свой_референс_только_правки(self) -> None:
        м = маршрут({"task": "generate", "inputs": [свой("image")], "outputs": ["image"], "shots": 6, "characters": 1})
        self.assertEqual(("редактирование_изображения",), м.шаги)

    def test_цена_референса_за_одну_картинку(self) -> None:
        итог = план({"task": "generate", "inputs": [], "outputs": ["image"], "shots": 24, "characters": 1})
        смета = {ш["step"]: ш for ш in итог["pipeline_price"]["смета"]["steps"]}
        self.assertEqual(0.05, смета["генерация_изображения"]["usd"])
        self.assertEqual(
            "24 pictures are edits from the reference (not 24 independent generations); the alternative is "
            "training a LoRA on the character",
            итог["steps"][1]["inferred"],
        )


# --- 9. Бюджет --------------------------------------------------------------------


class Бюджет(unittest.TestCase):
    def test_ноль_не_pass_при_платном_плане(self) -> None:
        """w33: «no budget at all» и картинка за 0.05 usd."""
        итог = план({"task": "generate", "inputs": [], "outputs": ["image"], "shots": 1, "budget": {"amount": 0, "currency": "USD"}})
        self.assertEqual(
            ("fail", "дороже_потолка", "fail", "over the ceiling"),
            (итог["outcome"], итог["reason"], итог["budget"]["outcome"], итог["budget"]["verdict"]),
        )

    def test_строка_бюджета_согласна_со_сметой(self) -> None:
        """n05: `budget: pass` рядом с `fail дороже_потолка`."""
        итог = план({"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 60, "budget": {"amount": 1, "currency": "USD"}})
        self.assertEqual(("fail", "fail"), (итог["outcome"], итог["budget"]["outcome"]))
        итог = план({"task": "generate", "inputs": [], "outputs": ["image"], "shots": 2, "budget": {"amount": 1, "currency": "USD"}})
        self.assertEqual(("pass", "fits the ceiling"), (итог["budget"]["outcome"], итог["budget"]["verdict"]))

    def test_пересчёт_вызывающего(self) -> None:
        spec, ошибки = bs.parse_spec({"budget": {"amount": 500, "currency": "JPY", "usd": 3.3}})
        self.assertEqual(([], 3.3, 500.0, "JPY"), (ошибки, spec.budget_usd, spec.budget_amount, spec.budget_currency))
        spec, _ = bs.parse_spec({"budget": {"amount": 500, "currency": "JPY"}})
        self.assertIsNone(spec.budget_usd)
        _, ошибки = bs.parse_spec({"budget": {"amount": 5, "currency": "USD", "rate": 1}})
        self.assertEqual(["spec.budget: unknown field(s) rate (known: amount, currency, usd)"], ошибки)

    def test_плата_за_клон_складывается(self) -> None:
        ставки = pricing.rates("$1.5 per clone, $0.3 per 1000 preview characters", "price")
        (вариант,) = pricing.estimate(ставки, pricing.Need(seconds=90, chars=1350))
        self.assertEqual(1.905, вариант.usd)
        (вариант,) = pricing.estimate(ставки, pricing.Need(seconds=90))
        self.assertEqual((1.5, "посчитана только плата за клон: прочие ставки шага к брифу не привязались"), (вариант.usd, вариант.lower_bound))


# --- 1. Бриф любой письменности ------------------------------------------------------


class ЛюбаяПисьменность(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["STUDIO_NO_JOURNAL"] = "1"

    def test_японский_бриф_с_полной_spec_планируется(self) -> None:
        from studio.mcp import server

        итог = json.loads(
            server.plan_pipeline(
                "商品写真10枚から背景を白に差し替えた画像を作りたい、予算は500円",
                spec={"task": "edit", "inputs": [{"kind": "image", "owned": True, "count": 10}], "outputs": ["image"], "shots": 10},
            )
        )
        self.assertEqual((["редактирование_изображения"], False), ([ш["step"] for ш in итог["steps"]], итог["brief_screened"]))
        self.assertNotEqual("pass", итог["outcome"])

    def test_слова_любой_письменности(self) -> None:
        from studio.mcp import server

        self.assertEqual(
            (True, True, False, False),
            tuple(server.есть_слова(т) for т in ("为我们的茶叶品牌", "สวัสดี", "!!! 123", "")),
        )

    def test_непрочитанный_просевом_бриф_не_pass(self) -> None:
        from studio.mcp import server

        итог = server._просев_не_читал({"outcome": "pass", "unmeasured": 0, "note": "plan stands"})
        self.assertEqual(
            ("could not measure", 1, False, "plan stands. " + server.NOTE_SCRIPT_NOT_SCREENED),
            (итог["outcome"], итог["unmeasured"], итог["brief_screened"], итог["note"]),
        )
        self.assertEqual("fail", server._просев_не_читал({"outcome": "fail"})["outcome"])

    def test_пустой_бриф_без_spec_по_прежнему_пуст(self) -> None:
        from studio.mcp import server

        self.assertEqual("бриф_пуст", json.loads(server.plan_pipeline("!!! 123"))["reason"])


if __name__ == "__main__":
    unittest.main()
