"""Round 15 integration: the knowledge rules (`checklist.RULES_R15`, round-15 pricing) read the
spec fields of round 15 (`outputs[]` objects, `consistency`, `edit_target`, `people[].speaks`,
`training_use`) in a brief in ANY language.

Every brief here is in Chinese, Japanese, Spanish or German and carries none of the EN/RU cue
words: each case is checked twice, WITH the field (the caveat / the price follows) and WITHOUT it
(silent) — so only the field triggers. Paraphrases written for this file, never a dev or holdout
brief. No network (T4).
"""

from __future__ import annotations

import json
import os
import unittest

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import expert_r15 as x15  # noqa: E402
from studio.mcp import server  # noqa: E402
from studio.recipes import apply as ra  # noqa: E402
from studio.recipes import checklist as cl  # noqa: E402
from studio.recipes import table as rt  # noqa: E402

_PLANS: dict[str, dict] = {}


def plan(brief: str, spec: dict) -> dict:
    ключ = brief + json.dumps(spec, sort_keys=True, ensure_ascii=False)
    if ключ not in _PLANS:
        _PLANS[ключ] = json.loads(server.plan_pipeline(brief, spec=spec))
    return _PLANS[ключ]


def notes(d: dict) -> list[str]:
    return [str(n.get("id")) for n in d.get("production_notes") or []]


def steps_of(d: dict) -> list[str]:
    return [str(ш.get("step")) for ш in d.get("steps") or []]


def clip_usd(d: dict) -> float:
    цена = d.get("pipeline_price") or {}
    return float((цена.get("за_ролик") or {}).get("usd") or (цена.get("смета") or {}).get("usd") or 0.0)


def _spec(raw: dict) -> bs.Spec:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    return spec


def fired(raw: dict, steps: list[str], brief: str) -> list[str]:
    return [i for i, _ in cl.fire(_spec(raw), steps, text=brief)]


def w(base: dict, **more: object) -> dict:
    return {**base, **more}


# Briefs: zh / ja / es / de, none of them with an EN or RU cue word for the decision under test.
ZH_RAIN = "咖啡馆窗外下雨的画面，三个小时，给我们的频道当背景"
JA_LOGO = "カフェのロゴがゆっくり回る短い映像、店内のモニター用"
ES_TEXTURE = "textura de piedra para el suelo de nuestro videojuego"
DE_SET = "zwölf Illustrationen für unser Kinderbuch über einen Fuchs"
ES_INSERT = "nuestra lata de refresco sobre la mesa en este vídeo que ya grabamos"
DE_SHORT = "ein kurzes Video für unsere Turnschuhe, eine Tänzerin im Studio"
ZH_DATASET = "为我们的模型生成五百张不同光线下的猫的照片"

GEN = {"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 15, "people": []}
LONG = w(GEN, duration_s=10800)
IMG = {"task": "generate", "inputs": [], "outputs": ["image"], "shots": 1, "people": []}
SET = w(IMG, shots=12)
EDV = {"task": "video-edit", "inputs": [{"kind": "video", "owned": True, "duration_s": 10}, {"kind": "image", "owned": True}],
       "outputs": ["video"], "duration_s": 10, "people": []}
DANCER = [{"name": "dancer", "real": False, "on_screen": True, "speaks": False}]


class ТолькоПолеРешает(unittest.TestCase):
    """Each round-15 caveat fires on its field in a non-EN/RU brief, and stays silent without it."""

    CASES: list[tuple[str, dict, dict, list[str], str]] = [
        # rule, spec WITH the field, spec WITHOUT it, steps, brief
        ("long_ambient_loop", w(LONG, outputs=[{"kind": "video", "loop": True}]), LONG, ["генерация_видео"], ZH_RAIN),
        ("seamless_loop", w(GEN, outputs=[{"kind": "video", "loop": True}]), GEN, ["генерация_видео"], JA_LOGO),
        ("tileable_texture", w(IMG, outputs=[{"kind": "image", "tileable": True}]), IMG, ["генерация_изображения"], ES_TEXTURE),
        ("style_consistency_set", w(SET, consistency=["style"]), SET, ["генерация_изображения"], DE_SET),
        ("product_insertion", w(EDV, edit_target="object"), EDV, ["правка_видео"], ES_INSERT),
        ("no_speech_short", w(GEN, people=DANCER), w(GEN, people=[{"name": "dancer", "real": False}]),
         ["генерация_видео"], DE_SHORT),
    ]

    def test_поле_включает_слова_нет(self) -> None:
        for rid, с_полем, без_поля, steps, brief in self.CASES:
            with self.subTest(rule=rid):
                self.assertIn(rid, fired(с_полем, steps, brief))
                self.assertNotIn(rid, fired(без_поля, steps, brief))

    def test_петля_звука_ja(self) -> None:
        # The loop field on an ambience (sfx) output: the seam caveat, in a brief without loop words.
        raw = {"task": "generate", "inputs": [], "outputs": ["sfx"], "duration_s": 600, "people": []}
        brief = "瞑想アプリ用の夜の湖の音、十分間"
        self.assertIn("seamless_loop", fired(w(raw, outputs=[{"kind": "sfx", "loop": True}]), ["звук_фон"], brief))
        self.assertNotIn("seamless_loop", fired(raw, ["звук_фон"], brief))
        self.assertIn("seamless_loop", notes(plan(brief, w(raw, outputs=[{"kind": "sfx", "loop": True}]))))

    def test_ложное_поле_глушит(self) -> None:
        self.assertNotIn("long_ambient_loop", fired(w(LONG, outputs=[{"kind": "video", "loop": False}]),
                                                    ["генерация_видео"], ZH_RAIN + "，雨声 ambient loop"))
        self.assertNotIn("tileable_texture", fired(w(IMG, outputs=[{"kind": "image", "tileable": False}]),
                                                   ["генерация_изображения"], "seamless tileable texture"))
        self.assertNotIn("style_consistency_set", fired(w(SET, consistency=["character"]),
                                                        ["генерация_изображения"], "in a consistent style"))
        self.assertNotIn("product_insertion", fired(w(EDV, edit_target="text"), ["правка_видео"], ES_INSERT))
        self.assertNotIn("no_speech_short", fired(w(GEN, people=[{**DANCER[0], "speaks": True}]),
                                                  ["генерация_видео"], "no voiceover, music only"))

    def test_удаление_предмета_не_вставка(self) -> None:
        # edit_target=object names WHAT changes; an object removed is not a product placed.
        self.assertNotIn("product_insertion", fired(w(EDV, edit_target="object", edit=["remove-object"]),
                                                    ["правка_видео"], ES_INSERT))

    def test_обучение_по_полю(self) -> None:
        raw = w(IMG, shots=500)
        self.assertTrue(cl.context(_spec(w(raw, training_use=True)), ["генерация_изображения"], ZH_DATASET).says(cl.W_TRAINING_DATA))
        self.assertFalse(cl.context(_spec(raw), ["генерация_изображения"], ZH_DATASET).says(cl.W_TRAINING_DATA))
        self.assertFalse(cl.context(_spec(w(raw, training_use=False)), ["генерация_изображения"],
                                    "training data for our model").says(cl.W_TRAINING_DATA))


class ЦенаПетли(unittest.TestCase):
    """The loop field prices the loop: one segment, not the full length."""

    def test_длинный_фон_zh(self) -> None:
        с = plan(ZH_RAIN, w(LONG, outputs=[{"kind": "video", "loop": True}]))
        без = plan(ZH_RAIN, LONG)
        self.assertIn("long_ambient_loop", notes(с))
        self.assertNotIn("long_ambient_loop", notes(без))
        self.assertIn("генерация_видео", steps_of(с))
        self.assertGreater(clip_usd(без), 10 * clip_usd(с))
        self.assertEqual(float(x15.AMBIENT_VIDEO_SEGMENT_S),
                         x15.ambient_segment_s(_spec(w(LONG, outputs=[{"kind": "video", "loop": True}])), ZH_RAIN, audio=False))
        self.assertIsNone(x15.ambient_segment_s(_spec(LONG), ZH_RAIN, audio=False))

    def test_короткая_петля_ja(self) -> None:
        с = _spec(w(GEN, outputs=[{"kind": "video", "loop": True}]))
        self.assertEqual(float(rt.LOOP_CLIP_S), ra.loop_seconds(с, JA_LOGO))
        self.assertIsNone(ra.loop_seconds(_spec(GEN), JA_LOGO))
        d = plan(JA_LOGO, w(GEN, outputs=[{"kind": "video", "loop": True}]))
        self.assertIn("seamless_loop", notes(d))
        self.assertNotIn("seamless_loop", notes(plan(JA_LOGO, GEN)))


class ПланПоПолю(unittest.TestCase):
    """End to end through plan_pipeline: the notes the field brings, in a non-EN/RU brief."""

    def test_тайл_es(self) -> None:
        self.assertIn("tileable_texture", notes(plan(ES_TEXTURE, w(IMG, outputs=[{"kind": "image", "tileable": True}]))))
        self.assertNotIn("tileable_texture", notes(plan(ES_TEXTURE, IMG)))

    def test_стиль_серии_de(self) -> None:
        self.assertIn("style_consistency_set", notes(plan(DE_SET, w(SET, consistency=["style"]))))
        self.assertNotIn("style_consistency_set", notes(plan(DE_SET, SET)))

    def test_вставка_товара_es(self) -> None:
        d = plan(ES_INSERT, w(EDV, edit_target="object"))
        self.assertIn("product_insertion", notes(d))
        self.assertNotIn("product_insertion", notes(plan(ES_INSERT, EDV)))
        from studio import planner

        модели = [str((ш.get("chosen") or {}).get("model") or "") for ш in d.get("steps") or []]
        self.assertFalse(any(planner.персонажная_замена(м) for м in модели if м), модели)

    def test_шортс_без_речи_de(self) -> None:
        d = plan(DE_SHORT, w(GEN, people=DANCER))
        self.assertIn("no_speech_short", notes(d))
        self.assertNotIn("липсинк", steps_of(d))
        self.assertNotIn("no_speech_short", notes(plan(DE_SHORT, w(GEN, people=[{"name": "dancer", "real": False}]))))


if __name__ == "__main__":
    unittest.main()
