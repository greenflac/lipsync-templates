"""Тесты studio.shoot: каждое правило ловит свой дефект и молчит на чистом плане.

Дефекты взяты из того, что владелец увидел и услышал 2026-10-07 (см. докстринг
пакета): склейка внутри генерации, голый наезд без оператора, «pores and sweat
sheen», UFC на перчатках, перепрыгнутая ось. Негативный контроль — сам
продакшн-файл ролика, который обязан проходить без единого замечания, и
синтетические кадры, на которых замер не должен находить того, чего нет.
"""

from __future__ import annotations

import dataclasses
import unittest
from pathlib import Path

import numpy as np

from studio.shoot import qa, validate
from studio.shoot.camera import RIGS
from studio.shoot.compile import compile_shot
from studio.shoot.h3graph import build, frames
from studio.shoot.spec import Beat, Line, Placement, Production, load

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = ROOT / "productions" / "augustvpn_main_event" / "production.json"


def _prod() -> Production:
    return load(PRODUCTION)


def _with_shot(prod: Production, i: int, **kw: object) -> Production:
    shots = list(prod.shots)
    shots[i] = dataclasses.replace(shots[i], **kw)  # type: ignore[arg-type]
    return dataclasses.replace(prod, shots=tuple(shots))


def _rules(prod: Production) -> set[str]:
    return {f.rule for f in validate.check(prod) if f.severity == validate.VIOLATION}


class NegativeControl(unittest.TestCase):
    def test_production_passes_clean(self) -> None:
        found = validate.check(_prod())
        self.assertEqual(found, [], [f.message for f in found])
        self.assertEqual(validate.outcome(found), "годно")

    def test_every_rig_has_motion_expectation(self) -> None:
        self.assertEqual(set(qa.RIG_MOTION), set(RIGS))


class PlantedDefects(unittest.TestCase):
    def setUp(self) -> None:
        self.prod = _prod()
        self.i = next(i for i, s in enumerate(self.prod.shots) if s.id == "S04_faceoff_wide")
        self.shot = self.prod.shots[self.i]

    def _beats(self, *extra: Beat) -> tuple[Beat, ...]:
        return (*self.shot.beats, *extra)

    def test_cut_inside_generation(self) -> None:
        p = _with_shot(self.prod, self.i, beats=self._beats(Beat(4, "action", "Cut to {adgar}.")))
        self.assertIn("cut", _rules(p))
        p = _with_shot(self.prod, self.i, framing="[Shot 2] close-up")
        self.assertIn("cut", _rules(p))

    def test_camera_without_operator(self) -> None:
        beats = tuple(b for b in self.shot.beats if b.kind != "camera") + (
            Beat(1, "camera", "Very slow push-in."),
        )
        rules = _rules(_with_shot(self.prod, self.i, beats=beats))
        self.assertIn("operator", rules)
        self.assertIn("bare_push", rules)

    def test_push_with_operator_is_allowed(self) -> None:
        beats = self._beats(Beat(6, "camera", "The operator follows him with a slow push-in."))
        self.assertNotIn("bare_push", _rules(_with_shot(self.prod, self.i, beats=beats)))

    def test_rig_missing_or_unknown(self) -> None:
        self.assertIn("rig", _rules(_with_shot(self.prod, self.i, rig="")))
        self.assertIn("rig", _rules(_with_shot(self.prod, self.i, rig="drone")))

    def test_skin_words(self) -> None:
        p = _with_shot(self.prod, self.i, framing="extreme close-up, pores and sweat sheen")
        self.assertIn("skin", _rules(p))

    def test_real_brand(self) -> None:
        p = _with_shot(self.prod, self.i, soundscape="An ESPN crowd mic.")
        self.assertIn("brand", _rules(p))
        p = _with_shot(self.prod, self.i, beats=self._beats(Beat(6, "action", "NordVPN banner.")))
        self.assertIn("brand", _rules(p))

    def test_violence(self) -> None:
        p = _with_shot(self.prod, self.i, beats=self._beats(Beat(6, "action", "Blood on canvas.")))
        self.assertIn("violence", _rules(p))

    def test_duration_window(self) -> None:
        self.assertIn("duration", _rules(_with_shot(self.prod, self.i, seconds=20)))
        self.assertIn("duration", _rules(_with_shot(self.prod, self.i, seconds=3)))

    def test_beat_after_end(self) -> None:
        p = _with_shot(self.prod, self.i, beats=self._beats(Beat(9, "action", "x")))
        self.assertIn("timing", _rules(p))

    def test_manual_subject_numbers(self) -> None:
        p = _with_shot(self.prod, self.i, framing="<Subject 1> alone")
        self.assertIn("subject", _rules(p))
        p = _with_shot(self.prod, self.i, framing="{announcer} watches")
        self.assertIn("subject", _rules(p))

    def test_speech_too_fast(self) -> None:
        long = " ".join(["word"] * 40)
        p = _with_shot(self.prod, self.i, dialogue=(Line(1, "referee", long),))
        self.assertIn("pace", _rules(p))

    def test_axis_jump(self) -> None:
        j = self.i + 1
        nxt = self.prod.shots[j]
        flipped = tuple(
            dataclasses.replace(
                b, screen={"left": "right", "right": "left"}.get(b.screen, b.screen)
            )
            for b in nxt.blocking
        )
        p = _with_shot(self.prod, j, blocking=flipped)
        self.assertIn("axis", _rules(p))
        p = _with_shot(p, j, crossing=True)
        self.assertNotIn("axis", _rules(p))

    def test_singles_look_same_way(self) -> None:
        a = dataclasses.replace(
            self.shot, id="X1", blocking=(Placement("august", "center", "right"),)
        )
        b = dataclasses.replace(
            self.shot, id="X2", blocking=(Placement("adgar", "center", "right"),)
        )
        p = dataclasses.replace(self.prod, shots=(a, b))
        self.assertIn("eyeline", _rules(p))
        b2 = dataclasses.replace(b, blocking=(Placement("adgar", "center", "left"),))
        self.assertNotIn("eyeline", _rules(dataclasses.replace(self.prod, shots=(a, b2))))


class Compiler(unittest.TestCase):
    def test_prompt_sections_and_refs(self) -> None:
        prod = _prod()
        shot = next(s for s in prod.shots if s.id == "S04_faceoff_wide")
        c = compile_shot(prod, shot)
        for section in (
            "subject_definitions:",
            "summary:",
            "retention_analysis:",
            "detailed_description:",
            "overall_soundscape:",
            "non_diegetic_music:",
        ):
            self.assertIn(section, c.prompt)
        self.assertNotIn("{", c.prompt)
        self.assertIn("One continuous take, no cuts", c.prompt)
        self.assertIn(RIGS[shot.rig].operator, c.prompt)
        self.assertIn("27 cm taller", c.prompt)
        self.assertEqual(c.prompt.count("cm taller"), 1)
        self.assertEqual(len(c.refs), 6)
        self.assertEqual(Path(c.refs[-1]).name, "ref_canvas_security_arena.png")
        self.assertIn("The floor is printed exactly like <Picture 6>", c.prompt)
        self.assertIn("gloves are plain matte black", c.prompt)

    def test_no_gloves_on_the_announcer(self) -> None:
        # S01_announce, 2026-10-07: фраза о перчатках надела перчатку конферансье
        prod = _prod()
        c = compile_shot(prod, next(s for s in prod.shots if s.id == "S01_announce"))
        self.assertNotIn("glove", c.prompt)

    def test_set_ref_only_in_its_scenes(self) -> None:
        prod = _prod()
        c = compile_shot(prod, next(s for s in prod.shots if s.id == "S08_booth"))
        self.assertEqual(c.refs, ())
        self.assertTrue(all((PRODUCTION.parent / r).exists() for r in c.refs))

    def test_graph_wires_every_ref(self) -> None:
        prod = _prod()
        c = compile_shot(prod, prod.shots[3])
        g = build(c, "shoot/x")
        cond = g["10"]["inputs"]
        self.assertEqual(sum(k.startswith("ref_images.") for k in cond), len(c.refs))
        self.assertEqual(cond["length"], frames(c.seconds))
        self.assertEqual(frames(5) % 17, 5)
        self.assertNotIn("6", g)  # realism LoRA выключена по умолчанию


def _texture(h: int, w: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = rng.normal(0, 1, (h, w))
    k = np.ones(3) / 3
    for ax in (0, 1):
        t = np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), ax, t)
    return (t - t.min()) / (t.max() - t.min()) * 255


def _crop(img: np.ndarray, cx: float, cy: float, scale: float, h: int, w: int) -> np.ndarray:
    ys = np.clip(np.round(cy + (np.arange(h) - h / 2) / scale).astype(int), 0, img.shape[0] - 1)
    xs = np.clip(np.round(cx + (np.arange(w) - w / 2) / scale).astype(int), 0, img.shape[1] - 1)
    return img[np.ix_(ys, xs)]


class Measure(unittest.TestCase):
    H, W, N = 160, 96, 48

    def setUp(self) -> None:
        self.big = _texture(400, 300, 1)

    def test_handheld_shake_vs_locked(self) -> None:
        rng = np.random.default_rng(2)
        shake = np.stack(
            [
                _crop(self.big, 150 + rng.normal(0, 2), 200 + rng.normal(0, 2), 1.0, self.H, self.W)
                for _ in range(self.N)
            ]
        )
        still = np.stack([_crop(self.big, 150, 200, 1.0, self.H, self.W)] * self.N)
        j_shake, _ = qa.jitter(qa.camera_path(shake), self.W)
        j_still, _ = qa.jitter(qa.camera_path(still), self.W)
        self.assertGreater(j_shake, qa.JITTER_HANDHELD_MIN)
        self.assertLess(j_still, qa.JITTER_LOCKED_MAX)

    def test_smooth_push_in_is_caught(self) -> None:
        push = np.stack(
            [
                _crop(self.big, 150, 200, 1.0 + 0.8 * i / (self.N - 1), self.H, self.W)
                for i in range(self.N)
            ]
        )
        path = qa.camera_path(push)
        self.assertGreater(qa.zoom(path), 1.5)
        verdict, notes = qa.judge("in_cage_handheld", 0.1, [], qa.zoom(path))
        self.assertEqual(verdict, "не годно")
        self.assertTrue(any("ИИ-наезд" in n for n in notes))
        # тот же наезд с дрожью рук — оператор шагнул ближе (op_A), это годно
        self.assertEqual(qa.judge("in_cage_handheld", 0.5, [], qa.zoom(path))[0], "годно")
        self.assertEqual(qa.judge("cage_side_tele", 0.5, [], qa.zoom(path))[0], "годно")

    def test_brand_lookalike_on_frame(self) -> None:
        # sc_S1, 2026-10-07: «OFC» на перчатках — подделка под UFC
        self.assertEqual(qa.brand_hits(["OFC", "SECURITYAREN"]), [("OFC", "UFC")])
        self.assertEqual(qa.brand_hits(["SECURITY ARENA", "FREE VPN", "АвгустVPN"]), [])

    def test_cut_found_and_no_false_cut(self) -> None:
        a = np.stack([_crop(self.big, 150, 200, 1.0, self.H, self.W)] * 24)
        b = np.stack([_texture(self.H, self.W, 9)] * 24)
        self.assertEqual(qa.cuts(np.concatenate([a, b])), [1.0])
        self.assertEqual(qa.cuts(a), [])


if __name__ == "__main__":
    unittest.main()
