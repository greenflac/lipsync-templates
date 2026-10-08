"""Тесты studio.shoot: каждое правило ловит свой дефект и молчит на чистом плане.

Дефекты взяты из того, что владелец увидел и услышал 2026-10-07 (см. докстринг
пакета): склейка внутри генерации, голый наезд без оператора, «pores and sweat
sheen», UFC на перчатках, перепрыгнутая ось. Негативный контроль — сам
продакшн-файл ролика, который обязан проходить без единого замечания, и
синтетические кадры, на которых замер не должен находить того, чего нет.
"""

from __future__ import annotations

import dataclasses
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from studio.shoot import journal, qa, validate
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
        self.i = next(i for i, s in enumerate(self.prod.shots) if s.id == "S05_faceoff")
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


class Reveal(unittest.TestCase):
    """2026-10-08: до развязки — настоящий бой, ни слова о продукте."""

    def test_product_word_before_reveal_is_caught(self) -> None:
        prod = _prod()
        i = next(k for k, s in enumerate(prod.shots) if s.id == "S08_booth")
        line = Line(0.5, "caster_a", "He is lagging like a free VPN!")
        found = validate.check(_with_shot(prod, i, dialogue=(line,)))
        self.assertIn("reveal", {f.rule for f in found if f.severity == validate.VIOLATION})

    def test_same_word_after_reveal_is_allowed(self) -> None:
        prod = _prod()
        i = next(k for k, s in enumerate(prod.shots) if s.id == "S10_disconnect")
        beats = (*prod.shots[i].beats, Beat(5.0, "action", "A free VPN logo glows."))
        self.assertNotIn("reveal", _rules(_with_shot(prod, i, beats=beats)))

    def test_word_vs_stem(self) -> None:
        pat = validate.secret_pattern(("lag", "бесплатн*"))
        assert pat is not None
        self.assertIsNone(pat.search("the frame lagging behind"))  # работа камеры, не продукт
        self.assertIsNotNone(pat.search("a lag"))
        self.assertIsNotNone(pat.search("бесплатного"))

    def test_edit_subtitle_before_reveal_is_caught(self) -> None:
        from studio.shoot import edit

        prod = _prod()
        e = edit.load(PRODUCTION.parent / "edit.json")
        c = e.clips[0]
        bad_sub = edit.Sub(0.1, 2.0, "Бесплатный против платного")
        e2 = dataclasses.replace(e, clips=(dataclasses.replace(c, subs=(bad_sub,)), *e.clips[1:]))
        found = edit.problems(
            e2,
            PRODUCTION.parent,
            {s.id for s in prod.shots},
            prod.reveal_from,
            validate.secret_pattern(prod.secret_words),
        )
        self.assertTrue(any("до развязки" in p for p in found), found)


class Compiler(unittest.TestCase):
    def test_prompt_sections_and_refs(self) -> None:
        prod = _prod()
        shot = next(s for s in prod.shots if s.id == "S05_faceoff")
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
        c = compile_shot(prod, next(s for s in prod.shots if s.id == "S02_announce"))
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
        self.assertTrue(any(n.startswith("масштаб кадра") for n in notes), notes)
        # тот же наезд с дрожью рук — оператор шагнул ближе (op_A), это годно
        self.assertEqual(qa.judge("in_cage_handheld", 0.5, [], qa.zoom(path))[0], "годно")
        self.assertEqual(qa.judge("cage_side_tele", 0.5, [], qa.zoom(path))[0], "годно")

    def test_brand_lookalike_on_frame(self) -> None:
        # sc_S1, 2026-10-07: «OFC» на перчатках — подделка под UFC
        self.assertEqual(qa.brand_hits(["OFC", "SECURITYAREN"]), [("OFC", "UFC")])
        self.assertEqual(qa.brand_hits(["SECURITY ARENA", "FREE VPN", "АвгустVPN"]), [])

    def test_threshold_sits_between_measured_takes(self) -> None:
        # замеры 2026-10-07 (studio/knowledge/measured.jsonl): ИИ-наезды и оператор
        ai_push = (0.281, 0.111, 0.256, 0.115)
        operator = (0.506, 0.330)
        self.assertLess(max(ai_push), qa.JITTER_HANDHELD_MIN)
        self.assertLess(qa.JITTER_HANDHELD_MIN, min(operator))

    def test_cut_found_and_no_false_cut(self) -> None:
        # живой план всегда немного меняется от кадра к кадру: зерно, движение
        rng = np.random.default_rng(5)
        base_a = _crop(self.big, 150, 200, 1.0, self.H, self.W)
        base_b = _texture(self.H, self.W, 9)
        a = np.stack([base_a + rng.normal(0, 2, base_a.shape) for _ in range(24)])
        b = np.stack([base_b + rng.normal(0, 2, base_b.shape) for _ in range(24)])
        self.assertEqual(qa.cuts(np.concatenate([a, b])), [1.0])
        self.assertEqual(qa.cuts(a), [])


class Journal(unittest.TestCase):
    JOURNAL = PRODUCTION.parent / "journal.jsonl"

    def test_production_journal_is_consistent(self) -> None:
        rows = journal.load(self.JOURNAL)
        self.assertGreater(len(rows), 10)
        self.assertEqual(journal.check(rows), [])

    def test_owner_remark_without_incident_is_caught(self) -> None:
        rows: list[dict[str, object]] = [
            {
                "id": "review-1",
                "ts": "t",
                "kind": "review",
                "stage": "camera",
                "by": "owner",
                "summary": "камера неживая",
                "outcome": "не годно",
            }
        ]
        self.assertTrue(any("без разбора" in p for p in journal.check(rows)))
        rows.append(
            {
                "id": "incident-1",
                "ts": "t",
                "kind": "incident",
                "stage": "camera",
                "by": "agent",
                "summary": "наезд",
                "from": ["review-1"],
                "cause": "промпт про движение, не про оператора",
                "rule": "studio/shoot/camera.py:RIGS",
            }
        )
        self.assertEqual(journal.check(rows), [])

    def test_incident_needs_rule_or_reason(self) -> None:
        ev = {"id": "i", "ts": "t", "kind": "incident", "stage": "look", "by": "agent"}
        ev |= {"summary": "x", "cause": "y"}
        self.assertTrue(any("правила" in p for p in journal.problems(ev)))
        self.assertEqual(journal.problems(ev | {"no_rule": "разовый сбой провайдера"}), [])

    def test_render_needs_outcome(self) -> None:
        ev = {"id": "r", "ts": "t", "kind": "render", "stage": "render", "by": "pipeline"}
        self.assertTrue(any("исхода" in p for p in journal.problems(ev | {"summary": "x"})))

    def test_two_prices_in_summary(self) -> None:
        rows = [
            {"kind": "render", "gpu_s": 3600, "cost_usd": 2.0, "outcome": "годно", "shot": "A"},
            {"kind": "cost", "cost_usd": 8.0},
        ]
        s = journal.summarize(rows)
        self.assertEqual((s.render_cost_usd, s.cost_usd), (2.0, 8.0))
        self.assertIn("25%", journal.render_summary(s))


class Budget(unittest.TestCase):
    def test_batch_over_budget_is_refused(self) -> None:
        from studio.shoot.render import budget_problem, estimate_usd

        prod = dataclasses.replace(_prod(), budget_usd=10.0)
        ids = [s.id for s in prod.shots]
        rows = [{"kind": "cost", "cost_usd": 9.5}]
        need = estimate_usd(prod, ids, rows, 2.09)
        self.assertGreater(need, 0.5)
        self.assertIn("осталось $0.50", budget_problem(10.0, prod, ids, rows, 2.09))
        self.assertEqual(budget_problem(100.0, prod, ids, rows, 2.09), "")
        self.assertEqual(budget_problem(0.0, prod, ids, rows, 2.09), "")  # бюджет не задан

    def test_rate_learned_from_journal(self) -> None:
        from studio.shoot.render import DEFAULT_GPU_S_PER_S, gpu_s_per_second

        self.assertEqual(gpu_s_per_second([]), DEFAULT_GPU_S_PER_S)
        rows = [{"kind": "render", "gpu_s": 186, "seconds": 5}]
        self.assertAlmostEqual(gpu_s_per_second(rows), 37.2)

    def test_render_event_records_what_reproduces_the_take(self) -> None:
        from studio.shoot.render import render_event

        prod = _prod()
        c = compile_shot(prod, prod.shots[3])
        ev = render_event(c, "cage_side_tele", 413, "годно", "x.mp4", 2.09, build(c, "p"))
        self.assertEqual(journal.problems(ev | {"id": "r", "ts": "t"}), [])
        self.assertEqual(len(ev["prompt_sha"]), 12)
        self.assertEqual(ev["seed"], c.seed)
        self.assertAlmostEqual(ev["cost_usd"], 0.2398, places=3)


class Edit(unittest.TestCase):
    EDIT = PRODUCTION.parent / "edit.json"

    def test_edit_sheet_is_clean_and_about_forty_seconds(self) -> None:
        from studio.shoot import edit

        e = edit.load(self.EDIT)
        shots = {s.id for s in _prod().shots}
        self.assertEqual(edit.problems(e, self.EDIT.parent, shots), [])
        self.assertTrue(38.0 <= e.length <= 45.0, e.length)  # ТЗ: около 40 с
        used = {c.shot for c in e.clips if not c.still}
        self.assertEqual(used, shots)  # каждый снятый план в монтаже

    def test_subtitle_too_fast_or_wide_is_caught(self) -> None:
        from studio.shoot import edit

        e = edit.load(self.EDIT)
        c = e.clips[0]
        long = edit.Sub(0.1, 1.0, "Очень длинная реплика, которую никто не успеет прочитать")
        bad = dataclasses.replace(e, clips=(dataclasses.replace(c, subs=(long,)),))
        found = edit.problems(bad, self.EDIT.parent, {c.shot})
        self.assertTrue(any("не успеть прочитать" in p for p in found), found)
        if Path(edit.FONT).exists():
            self.assertTrue(any("шире кадра" in p for p in found), found)

    def test_global_graphics_follow_shots_not_seconds(self) -> None:
        from studio.shoot import edit

        e = edit.load(self.EDIT)
        starts, t = {}, 0.0
        for c in e.clips:
            starts[c.shot] = t
            t += c.length
        bug = next(o for o in e.global_overlays if "scorebug" in o.img)
        self.assertAlmostEqual(bug.t, starts["S06_bell_charge"], places=6)
        self.assertTrue(edit.is_video(bug.img))

    def test_watermark_is_separate_and_removable(self) -> None:
        from studio.shoot import edit

        e = edit.load(self.EDIT)
        self.assertIsNotNone(e.watermark)
        self.assertNotIn(e.watermark, e.global_overlays)  # снимается флагом, лист не трогаем

    def test_slate_wraps_lines(self) -> None:
        from studio.shoot.edit import _wrap

        lines = _wrap("S07 · нет рендера\nFASTER: the free VPN lags; a stutter is added", 20)
        self.assertEqual(lines[0], "S07 · нет рендера")
        self.assertTrue(all(len(x) <= 20 for x in lines[1:]))

    @unittest.skipUnless(shutil.which("ffmpeg"), "нет ffmpeg")
    def test_assemble_slates_and_still(self) -> None:
        from studio.shoot import edit

        with tempfile.TemporaryDirectory() as tmp:
            e = edit.Edit(
                clips=(
                    edit.Clip("S02_announce", 0.0, 0.5),
                    edit.Clip("packshot", 0.0, 0.5, still="gfx/packshot.webm"),
                )
            )
            out = Path(tmp) / "m.mp4"
            slates = edit.assemble(e, self.EDIT.parent, {}, {}, out)
            self.assertEqual(slates, ["S02_announce"])
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
