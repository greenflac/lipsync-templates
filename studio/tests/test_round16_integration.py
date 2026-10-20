"""Round 16 integration: the spec-field round (`spec_first`, `anonymise`) meets the expertise round
(`expert_r16`). Each case is an interaction of a decision of one branch with one of the other.

1. `anonymise.voice` on a DRAWN dub: the voice route (transcript + a different stock voice) wins;
   no dub, no optional lip-sync upgrade, no "adapted to the mouth flaps" assembly line.
2. `outputs[].spatial` beside the other `outputs[]` flags (loop, tileable, alpha): every flag parses
   on its own item, each caveat fires, and the field is offered in `spec_needed` like the others.
3. The video-edit TIER swap beside a face-swap anonymisation: an edit whose named target is not the
   person stays on the route (with its tier swap) next to the face route.
4. `voiceover: false` and the narrated-series key visuals: a piece named without narration is not a
   narrated series by the words; `consistency: ["style"]` still decides by itself.

Every case is a paraphrase written for this file, never a dev or holdout brief. No network (T4).
"""

from __future__ import annotations

import json
import os
import unittest
from typing import Any

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import anonymise as an  # noqa: E402
from studio import brief_spec as bs  # noqa: E402
from studio import expert_r16 as x16  # noqa: E402
from studio.mcp import server  # noqa: E402
from studio.recipes import apply as ra  # noqa: E402
from studio.recipes import checklist as cl  # noqa: E402

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


def notes(d: dict) -> list[str]:
    return [str(н.get("id")) for н in d.get("production_notes") or []]


def assembly(d: dict) -> list[str]:
    return [str(с) for с in (d.get("assembly") or {}).get("why") or []]


def _spec(raw: dict) -> bs.Spec:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    return spec


def applied(brief: str, raw: dict) -> ra.Applied:
    spec = bs.with_defaults(_spec(raw), ролик=True, текст=brief)
    return ra.rewrite(spec, bs.route(spec), brief)


def w(base: dict, **more: Any) -> dict:
    return {**base, **more}


DUB = {"task": "dub-translate", "inputs": [{"kind": "video", "owned": True, "duration_s": 1320}], "outputs": ["video", "speech"],
       "duration_s": 1320, "languages": ["es"], "conditions": ["anime"],
       "people": [{"name": "hero", "real": False, "on_screen": True, "speaks": True}]}
SFX = {"task": "generate", "inputs": [], "outputs": ["sfx"], "duration_s": 120, "languages": [], "people": []}
EDV = {"task": "video-edit", "inputs": [{"kind": "video", "owned": True, "duration_s": 30}], "outputs": ["video"], "duration_s": 30,
       "edit_target": "background", "languages": [], "people": []}
SER = {"task": "generate", "inputs": [], "outputs": ["video", "speech"], "shots": 20, "per_shot_s": 9, "languages": ["en"],
       "people": []}


# --- 1. anonymise.voice + drawn dub ------------------------------------------------------------------


class ГолосВРисованномДубляже(unittest.TestCase):
    BRIEF = "Dub our 22-minute anime episode into Spanish; the narrator's voice must not be recognisable"

    def test_маршрут_голоса_без_липсинка(self) -> None:
        а = applied(self.BRIEF, w(DUB, anonymise={"voice": True}))
        self.assertEqual(an.VOICE_STEPS, а.route.шаги)
        self.assertEqual((), а.optional)
        self.assertNotIn(ra.ASSEMBLY_DRAWN_ADAPT, а.assembly)
        self.assertNotIn(ra.ASSEMBLY_DRAWN_DUB, а.assembly)
        self.assertIn(an.ASSEMBLY_VOICE, а.assembly)

    def test_без_анонимизации_рисованный_дубляж_как_был(self) -> None:
        а = applied("Dub our 22-minute anime episode into Spanish", DUB)
        self.assertEqual((x16.OPTIONAL_LIPS_STEP,), а.optional)
        self.assertIn(ra.ASSEMBLY_DRAWN_ADAPT, а.assembly)
        а = applied("Dub our 22-minute anime episode into Spanish", w(DUB, anonymise=False))
        self.assertEqual((x16.OPTIONAL_LIPS_STEP,), а.optional)

    def test_план(self) -> None:
        d = plan(self.BRIEF, w(DUB, anonymise={"voice": True}))
        self.assertEqual(list(an.VOICE_STEPS), steps_of(d))
        self.assertFalse([у for у in d["pipeline_price"].get("conditional_steps") or [] if у.get("optional")])
        self.assertIn("voice_anonymisation", notes(d))
        self.assertNotIn("drawn_dub_adaptation", notes(d))
        self.assertNotIn(ra.ASSEMBLY_DRAWN_ADAPT[1], assembly(d))
        self.assertNotIn("OPTIONAL", d.get("summary", ""))


# --- 2. outputs[].spatial with the other outputs[] flags ----------------------------------------------


class ПространственныйСДругимиФлагами(unittest.TestCase):
    def test_флаги_на_своих_записях(self) -> None:
        spec = _spec(w(SFX, outputs=[{"kind": "video", "loop": True, "alpha": True}, {"kind": "sfx", "spatial": True},
                                     {"kind": "image", "tileable": True}]))
        self.assertEqual((True, True, True, True), (spec.loop, spec.alpha, spec.tileable, spec.spatial))
        spec = _spec(w(SFX, outputs=[{"kind": "sfx", "spatial": True, "loop": True}]))
        self.assertEqual((True, True, None), (spec.spatial, spec.loop, spec.alpha))

    def test_ошибка_называет_все_поля(self) -> None:
        _, errors = bs.parse_spec(w(SFX, outputs=[{"kind": "sfx", "spatial": True, "fps": 30}]))
        self.assertTrue(any("unknown field(s) fps" in e and "spatial" in e and "loop" in e for e in errors), errors)
        _, errors = bs.parse_spec(w(SFX, outputs=[{"kind": "sfx", "spatial": 1, "loop": "yes"}]))
        self.assertTrue(any("outputs[0].spatial" in e for e in errors), errors)
        self.assertTrue(any("outputs[0].loop" in e for e in errors), errors)

    def test_оговорки_вместе(self) -> None:
        d = plan("森林的声音，无缝循环", w(SFX, outputs=[{"kind": "sfx", "spatial": True, "loop": True}]))
        self.assertIn("spatial_audio", notes(d))
        self.assertIn("seamless_loop", notes(d))
        d = plan("x", w(SFX, outputs=[{"kind": "video", "loop": True, "alpha": True}, {"kind": "sfx", "spatial": True}]))
        for note in ("spatial_audio", "seamless_loop", "alpha_delivery"):
            self.assertIn(note, notes(d))

    def test_флаг_на_видео_не_звук(self) -> None:
        # The flag belongs to a SOUND output: the caveat stays silent without one.
        raw = w(SFX, outputs=[{"kind": "video", "spatial": True}])
        self.assertNotIn("spatial_audio", [i for i, _ in cl.fire(_spec(raw), ["генерация_видео"], text="x")])

    def test_вопрос_о_спецификации(self) -> None:
        self.assertIn("outputs[].spatial", bs.DECISION_FIELDS)
        self.assertIn("outputs[].spatial", bs.OPTIONAL_HELP)
        doc = " ".join((server.plan_pipeline.__doc__ or "").split())
        self.assertIn("spatial?: bool", doc)
        self.assertIn("{kind, loop?: bool, tileable?: bool, alpha?: bool}", doc)
        got = {f["field"]: f["read_from_text"] for f in bs.decision_fields("ambisonic forest bed for our VR piece")}
        self.assertIs(True, got["outputs[].spatial"])
        got = {f["field"]: f["read_from_text"] for f in bs.decision_fields("stereo rain")}
        self.assertIsNone(got["outputs[].spatial"])
        answer = json.loads(server.plan_pipeline("Ambiente sonoro de bosque para realidad virtual"))
        fields = [f["field"] for f in answer["spec_needed"]["draft"]["decision_fields"]]
        self.assertIn("outputs[].spatial", fields)
        self.assertIn("outputs[].spatial", answer["spec_needed"]["allowed"])


# --- 3. edit tier swap + anonymise face swap ------------------------------------------------------------


class СтупеньПравкиИАнонимизация(unittest.TestCase):
    BRIEF = "Replace the background of our 30 s street clip with a beach and hide the passers-by's faces"

    def test_правка_фона_остаётся_рядом_с_заменой_лиц(self) -> None:
        а = applied(self.BRIEF, w(EDV, anonymise={"faces": True}))
        self.assertEqual({*an.FACE_SWAP_STEPS, "правка_видео"}, set(а.route.шаги))
        а = applied(self.BRIEF, w(EDV, anonymise={"faces": True, "method": "blur"}))
        self.assertEqual(("правка_видео",), а.route.шаги)

    def test_правка_человека_и_без_цели_уходят(self) -> None:
        # The edit IS the anonymisation when it targets the person or names no target.
        for raw in (w(EDV, edit_target="person"), {k: v for k, v in EDV.items() if k != "edit_target"}):
            with self.subTest(target=raw.get("edit_target")):
                а = applied(self.BRIEF, w(raw, anonymise={"faces": True}))
                self.assertNotIn("правка_видео", а.route.шаги)

    def test_план_обмен_ступени_и_замена_лица(self) -> None:
        d = plan(self.BRIEF, w(EDV, anonymise={"faces": True}))
        swap = step(d, "правка_видео").get("budget_swap") or {}
        self.assertEqual(list(x16.REASON_EDIT_TIER), list(swap.get("reason") or []))
        self.assertEqual("wavespeed-video-face-swap", (step(d, "замена_персонажа").get("chosen") or {}).get("model"))
        self.assertIn("anonymisation_gdpr", notes(d))
        качество = plan(self.BRIEF, w(EDV, anonymise={"faces": True}, objective="quality"))
        self.assertNotIn("budget_swap", step(качество, "правка_видео"))

    def test_план_размытие_с_правкой(self) -> None:
        d = plan(self.BRIEF, w(EDV, anonymise={"faces": True, "method": "blur"}))
        self.assertEqual(["правка_видео"], steps_of(d))
        self.assertIn("budget_swap", step(d, "правка_видео"))
        self.assertTrue(any("blurred" in с for с in assembly(d)), assembly(d))


# --- 4. voiceover: false + narrated series key visuals -------------------------------------------------


class БезГолосаИСерия(unittest.TestCase):
    BRIEF = "An explainer series for our SaaS, 4 episodes"

    def test_слова_серии_не_читаются_без_голоса(self) -> None:
        self.assertTrue(x16.key_visual_words(_spec(SER), self.BRIEF))
        self.assertFalse(x16.key_visual_words(_spec(w(SER, voiceover=False)), self.BRIEF))
        self.assertTrue(x16.key_visual_words(_spec(w(SER, voiceover=True)), self.BRIEF))

    def test_маршрут(self) -> None:
        def шаги(raw: dict) -> tuple[str, ...]:
            return bs.route(bs.with_defaults(_spec(raw), ролик=True, текст=self.BRIEF)).шаги

        self.assertIn("генерация_изображения", шаги(SER))
        self.assertNotIn("генерация_изображения", шаги(w(SER, voiceover=False)))
        # The named field decides by itself, narration or not.
        self.assertIn("генерация_изображения", шаги(w(SER, voiceover=False, consistency=["style"])))
        self.assertIn("генерация_изображения", шаги(w(SER, outputs=["video"], voiceover=False, consistency=["style"])))

    def test_план_без_речи(self) -> None:
        d = plan(self.BRIEF + ", music only", w(SER, outputs=["video"], voiceover=False))
        self.assertIn("no_speech_short", notes(d))
        self.assertNotIn("style_consistency_set", notes(d))
        d = plan(self.BRIEF + ", music only", w(SER, outputs=["video"], voiceover=False, consistency=["style"]))
        self.assertIn("генерация_изображения", steps_of(d))
        self.assertIn("no_speech_short", notes(d))


if __name__ == "__main__":
    unittest.main()
