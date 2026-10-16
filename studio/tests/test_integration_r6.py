"""Интеграция шестого круга: spec доходит до политики людей, условий и правки видео.

Четыре ветки круга (реестр, find_models, люди, контракт spec) сходятся в
`plan_pipeline`. Здесь — то, что видно только на стыке:

* `spec.people` читает политика `screen` (поле теперь в `SPEC_FIELDS`):
  реальный публичный человек с политическим заявлением — отказ, CEO с
  согласием — план, вымышленный — план;
* `spec.conditions` идёт в ранжирование: липсинк профиля выбирает модель, у
  которой записан довод «за» по `pose_range`, и печатает его;
* `spec.edit` решает, ЧТО правит шаг правки видео: продление и референс его не
  выигрывают никогда, правка без эндпоинта — «не измерено», а не подмена;
* правка исходника перед апскейлом считается по кадру исходника.
"""

from __future__ import annotations

import json
import os
import unittest

from studio import brief_spec as bs
from studio import endpoints as ep
from studio import planner as pn
from studio.mcp import server


def _свой(kind: str, sec: float | None = None, **extra: object) -> dict:
    вход: dict = {"kind": kind, "owned": True, **extra}
    if sec:
        вход["duration_s"] = sec
    return вход


def _план(spec: dict, бриф: str = "please plan this clip") -> dict:
    return json.loads(server.plan_pipeline(бриф, spec=spec))


class ПодработыПравки(unittest.TestCase):
    def test_правка_по_звеньям_идентификатора(self) -> None:
        self.assertEqual(
            {ep.EDIT_REPLACE_OBJECT, ep.EDIT_REMOVE_OBJECT, ep.EDIT_REPLACE_SKY},
            set(ep.edit_intents("fal-ai/kling-video/o3/standard/video-to-video/edit")),
        )
        self.assertEqual({ep.EDIT_REFRAME}, set(ep.edit_intents("fal-ai/ltx-2.3/reframe")))
        self.assertEqual({ep.EDIT_REFRAME}, set(ep.edit_intents("fal-ai/ltx-2.3-quality/outpaint")))
        self.assertEqual(
            {ep.EDIT_REMOVE_OBJECT}, set(ep.edit_intents("fal-ai/ltx-2.3-quality/clean-plate"))
        )
        self.assertEqual({ep.EDIT_RELIGHT}, set(ep.edit_intents("minimax/h3-max/relight")))
        self.assertEqual(
            {ep.EDIT_RESTYLE}, set(ep.edit_intents("fal-ai/hunyuan-video/video-to-video"))
        )
        # «icedit» — одно звено, а не «edit».
        self.assertEqual(frozenset(), ep.edit_intents("ltx2.3-icedit-insight"))

    def test_новое_видео_не_правка(self) -> None:
        for ид in (
            "fal-ai/ltx-2.3/extend-video",
            "fal-ai/kling-video/o3/pro/video-to-video/reference",
            "fal-ai/kling-video/v3/pro/motion-control",
            "blackforestlabs/flux-3/extend-video/draft",
            "minimax/h3-max/3d-to-video",
        ):
            with self.subTest(ид=ид):
                self.assertTrue(ep.not_an_edit(ид))
                self.assertEqual(frozenset(), ep.edit_intents(ид))
        self.assertFalse(ep.not_an_edit("fal-ai/kling-video/o3/standard/video-to-video/edit"))

    def test_spec_edit_разбирается_и_ругается(self) -> None:
        понято, ошибки = bs.resolve("", {"task": "video-edit", "edit": ["Reframe", "stabilise"]})
        self.assertEqual([], ошибки)
        self.assertEqual(("reframe", "stabilise"), понято.edit)
        _, ошибки = bs.resolve("", {"task": "video-edit", "edit": ["teleport"]})
        self.assertTrue(any(о.startswith("spec.edit: 'teleport'") for о in ошибки), ошибки)


class ПравкаВидео(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["STUDIO_NO_JOURNAL"] = "1"

    def _шаг(self, правка: list[str] | None, **ещё: object) -> tuple[dict, dict]:
        spec: dict = {
            "task": "video-edit",
            "inputs": [_свой("video", 20)],
            "outputs": ["video"],
            **ещё,
        }
        if правка is not None:
            spec["edit"] = правка
        план = _план(spec)
        шаг = next(ш for ш in план["steps"] if ш["step"] == "правка_видео")
        return план, шаг

    def test_правка_без_названной_подработы_по_инструкции(self) -> None:
        _, шаг = self._шаг(None)
        модель = (шаг["chosen"] or {})["model"]
        self.assertIn(ep.EDIT_REPLACE_OBJECT, ep.edit_intents(модель), модель)
        self.assertEqual(
            "default (spec.edit not named): edit by instruction", шаг["edit"]["asked_from"]
        )

    def test_замена_неба_не_продление(self) -> None:
        _, шаг = self._шаг(["replace-sky"], resolution="4k")
        модель = (шаг["chosen"] or {})["model"]
        self.assertFalse(ep.not_an_edit(модель), модель)
        self.assertIn(ep.EDIT_REPLACE_SKY, ep.edit_intents(модель))
        for сосед in шаг["alternatives"]:
            self.assertFalse(ep.not_an_edit(сосед["model"]), сосед)
        self.assertGreater(шаг["edit"]["not_an_edit_count"], 0)

    def test_смена_кадра_берёт_рефрейм(self) -> None:
        _, шаг = self._шаг(["reframe"], aspect="16:9")
        модель = (шаг["chosen"] or {})["model"]
        self.assertIn(ep.EDIT_REFRAME, ep.edit_intents(модель), модель)

    def test_стабилизации_нет_ни_у_кого_её_делает_монтаж(self) -> None:
        """Седьмой круг: стабилизации нет ни у одного эндпоинта — её делает
        монтаж (vidstab / Gyroflow, 0 usd), а не шаг без кандидата."""
        план = _план({"task": "video-edit", "inputs": [_свой("video", 20)], "outputs": ["video"], "edit": ["stabilise"]})
        self.assertEqual(([], "could not measure", "только_монтаж"), (план["steps"], план["outcome"], план["reason"]))
        self.assertEqual(0.0, план["pipeline_price"]["смета"]["usd"])
        self.assertTrue(план["assembly"]["why"][0].startswith("stabilisation: ffmpeg vidstab"), план["assembly"])

    def test_правка_исходника_до_апскейла_по_кадру_исходника(self) -> None:
        """w07: правка 2.7K-ролика считалась по кадру 4K, до которого его поднимет апскейл."""
        план = _план(
            {
                "task": ["video-edit", "upscale"],
                "inputs": [_свой("video", 90, resolution="2.7k")],
                "outputs": ["video"],
                "resolution": "4k",
                "fps": 60,
                "edit": ["reframe"],
            }
        )
        смета = {ш["step"]: ш for ш in план["pipeline_price"]["смета"]["steps"]}
        правка = смета["правка_видео"]["formula"]
        # Рефрейм в реестре — `ltx-2.3-quality/outpaint` с ценой за мегапиксель:
        # кадр 2704x1520 = 4.11008 Мп, а не 3840x2160 = 8.2944 Мп.
        self.assertTrue(правка.startswith("4.11008 MP/frame"), правка)
        self.assertIn("[2160p]", смета["апскейл"]["formula"])

    def test_исходник_без_кадра_по_допущению(self) -> None:
        self.assertEqual(
            (2704, 1520),
            bs.source_frame(bs.resolve("", {"inputs": [_свой("video", resolution="2.7k")]})[0]),
        )
        self.assertIsNone(bs.source_frame(bs.resolve("", {"inputs": [_свой("video", 5)]})[0]))
        self.assertIn("правка_видео", pn.SOURCE_EDIT_STEPS)


class ЛюдиИУсловияПоSpec(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["STUDIO_NO_JOURNAL"] = "1"

    АВАТАР = {
        "task": "avatar",
        "inputs": [],
        "outputs": ["video", "speech"],
        "duration_s": 20,
        "languages": ["fr"],
    }

    def test_w11_политик_без_согласия_отказ(self) -> None:
        план = _план(
            {
                **self.АВАТАР,
                "people": [
                    {
                        "name": "Emmanuel Macron",
                        "real": True,
                        "public_figure": True,
                        "consent": "none",
                        "claim": "political",
                    }
                ],
            },
            "Macron announces the borders are closed, in French, 20 seconds",
        )
        self.assertEqual(
            ("fail", "запрещённая_тема", []), (план["outcome"], план["reason"], план["steps"])
        )
        self.assertEqual("refuse", план["people_policy"]["decision"])

    def test_ceo_с_согласием_план(self) -> None:
        план = _план(
            {
                **self.АВАТАР,
                "languages": ["en"],
                "people": [
                    {
                        "name": "our CEO",
                        "real": True,
                        "public_figure": False,
                        "consent": "stated",
                        "claim": "none",
                    }
                ],
            },
            "our CEO welcomes new staff, 20 seconds",
        )
        self.assertNotEqual("fail", план["outcome"])
        self.assertTrue(план["steps"])
        self.assertEqual(["our CEO"], план["people_policy"]["consent_recorded"])

    def test_вымышленный_план(self) -> None:
        план = _план(
            {
                **self.АВАТАР,
                "languages": ["en"],
                "people": [
                    {
                        "name": "Captain Nova",
                        "real": False,
                        "public_figure": False,
                        "consent": "unknown",
                    }
                ],
            },
            "a fictional space captain greets viewers, 20 seconds",
        )
        self.assertNotEqual("fail", план["outcome"])
        self.assertTrue(план["steps"])
        self.assertNotIn(
            (план.get("question") or {}).get("axis"), ("согласие_на_образ", "люди_в_заказе")
        )

    def test_профиль_липсинк_по_условию_spec(self) -> None:
        spec = {
            "task": "lipsync",
            "inputs": [_свой("video", 12), _свой("audio", 12)],
            "outputs": ["video"],
            "languages": ["en"],
            "conditions": ["profile face"],
        }
        план = _план(spec, "lip sync my clip, the speaker is in profile")
        шаг = план["steps"][0]
        self.assertEqual("sync-lipsync-v3", шаг["chosen"]["model"])
        self.assertTrue(
            шаг["chosen"]["condition_note"].startswith("for — pose_range"), шаг["chosen"]
        )
        self.assertEqual(["pose_range"], план["stated_conditions"]["understood"])
        без = _план({к: з for к, з in spec.items() if к != "conditions"}, "lip sync my clip")
        # СЕДЬМОЙ КРУГ (валидатор v7: w24, n15, n16): и без условия
        # `sync-lipsync-v3` (объявленная похвала, провалов нет) выше
        # `sync-lipsync` (записан провал рта) — но уже не условием, а полем
        # «провал против объявленной хорошей новости».
        self.assertEqual("sync-lipsync-v3", без["steps"][0]["chosen"]["model"])
        self.assertEqual("", без["steps"][0]["chosen"].get("condition_note", ""))


if __name__ == "__main__":
    unittest.main()
