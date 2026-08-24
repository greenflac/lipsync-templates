"""Отбор петель: арифметика стыка, подавление пересечений, три исхода."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from .. import framemath as fork_comfy
from .. import pose
from .. import fork_looper as fl
from ..fork_identity import FAIL, PASS, UNMEASURED

PERIOD = 44
NFRAMES = 96


def skeleton(phase, *, mode="arms", tired=0.0, amp=0.10, seen=()):
    ph = 2 * math.pi * phase
    ax, ay = amp * math.cos(ph), amp * math.sin(ph)
    lx = ly = 0.0
    if mode == "legs":
        lx, ly, ax, ay = ax, ay, 0.0, 0.0
    elif mode == "line":
        ax = 0.0
    elif mode == "legs_line":
        lx, ly, ax, ay = 0.0, ay, 0.0, 0.0
    pts = {
        "l_hip": (0.45, 0.60),
        "r_hip": (0.55, 0.60),
        "l_shoulder": (0.44, 0.40),
        "r_shoulder": (0.56, 0.40),
        "l_elbow": (0.40 + ax, 0.50 + ay + tired),
        "r_elbow": (0.60 - ax, 0.50 + ay + tired),
        "l_wrist": (0.38 + 2 * ax, 0.58 + 2 * ay + 2 * tired),
        "r_wrist": (0.62 - 2 * ax, 0.58 + 2 * ay + 2 * tired),
        "l_knee": (0.44 + lx, 0.75 + ly),
        "r_knee": (0.56 - lx, 0.75 + ly),
        "l_ankle": (0.44 + 2 * lx, 0.90 + 2 * ly),
        "r_ankle": (0.56 - 2 * lx, 0.90 + 2 * ly),
    }
    return {k: (x, y, 1.0 if (not seen or k in seen) else 0.0) for k, (x, y) in pts.items()}


def loop_sequence(n=NFRAMES, *, tire=0.0, mode="arms"):
    """Маятник: движение точно повторяется каждые PERIOD кадров."""
    return [skeleton(t / PERIOD, mode=mode, tired=tire * t) for t in range(n)]


def drift_sequence(n=NFRAMES, *, tire=0.002):
    """Монотонный дрейф: конфигурация уезжает в одну сторону, петли нет вовсе."""
    return [skeleton(0.25, tired=tire * t) for t in range(n)]


ANCHOR = ("l_hip", "r_hip", "l_shoulder", "r_shoulder")


def seated(points, tilt):
    """Та же механика движения, но ДРУГАЯ ПОСАДКА: конечности смещены целиком."""
    return {k: (x, y if k in ANCHOR else y + tilt, v) for k, (x, y, v) in points.items()}


def two_exercises(n=NFRAMES):
    """Первую половину работают руки, вторую — ноги в другой посадке."""
    return [
        skeleton(t / PERIOD, mode="arms")
        if t < n // 2
        else seated(skeleton(t / PERIOD, mode="legs", amp=0.2), 0.6)
        for t in range(n)
    ]


def two_exercises_second_is_perfect(n=NFRAMES, tire=0.0001):
    """Два упражнения, и второе замыкается ТОЧНЕЕ первого."""
    return [
        skeleton(t / PERIOD, mode="arms", tired=tire * t)
        if t < n // 2
        else seated(skeleton(t / PERIOD, mode="legs", amp=0.2), 0.6)
        for t in range(n)
    ]


def two_speeds(n=NFRAMES, tire=0.0001):
    """Два упражнения РАЗНОЙ СКОРОСТИ: медленное со сносом, потом быстрое."""
    return [
        skeleton(t / PERIOD, mode="arms", amp=0.03, tired=tire * t)
        if t < n // 2
        else seated(skeleton(t / PERIOD, mode="legs", amp=0.25), 0.6)
        for t in range(n)
    ]


def still_sequence(n=NFRAMES):
    """Человек не движется: ранжировать стыки нечем — исход «не смогли»."""
    return [skeleton(0.0) for _ in range(n)]


def norm(points):
    return fl.states([points])[0]


class Material:
    """Кадры на диске плюс подменные детектор поз и читалка пикселей."""

    def __init__(
        self,
        poses,
        *,
        size=(32, 32),
        missing=(),
        broken=False,
        people=None,
        cuts=(),
        blank=False,
        head_mode="возвращается",
        head_blind=(),
        head_broken=False,
    ):
        from PIL import Image

        self.dir = Path(tempfile.mkdtemp(prefix="looper_frames_"))
        self.calls = []
        self.gray_calls = []
        self.poses = poses
        self.missing = set(missing)
        self.broken = broken
        self.people = people or {}
        self.cuts = set(cuts)
        self.head_mode = head_mode
        self.head_blind = set(head_blind)
        self.head_broken = head_broken
        self.head_calls = []
        for k in range(len(poses)):
            f = self.dir / f"{k:04d}.png"
            if blank:
                f.touch()
            else:
                Image.new("RGB", size, (k * 2 % 256, 40, 200 - k % 200)).save(f)

    def reader(self, path):
        self.calls.append(path)
        idx = int(Path(path).stem)
        if self.broken:
            return {"points": None, "why": "mediapipe не установлен (фикстура)"}
        if idx in self.missing:
            return {"points": None, "why": "", "people": 0}
        return {"points": self.poses[idx], "why": "", "people": self.people.get(idx)}

    def gray(self, path):
        """Пиксели, ВЫВЕДЕННЫЕ ИЗ СКЕЛЕТА этого кадра, плюс скачок на резах."""
        import numpy as np

        self.gray_calls.append(path)
        idx = int(Path(path).stem)
        pts = self.poses[idx]
        body = (4.0 * sum(x + y for x, y, _ in pts.values())) if pts else 0.0
        base = body + sum(5.0 for c in self.cuts if idx > c)
        return np.full((8, 8), base, dtype="float64")

    def head(self, path):
        """Голова, ТРЕТЬЯ ТОЧКА ВНЕДРЕНИЯ. Настоящий детектор 133 точек"""
        import numpy as np

        self.head_calls.append(path)
        idx = int(Path(path).stem)
        if self.head_broken:
            return {"head": None, "why": "весов DWPose нет (фикстура)"}
        if idx in self.head_blind:
            return {"head": None, "why": ""}
        pts = self.poses[idx]
        if pts is None:
            return {"head": None, "why": ""}
        bob = 6.0 * float(np.sin(2 * np.pi * (idx % PERIOD) / PERIOD))
        x = 720 * (pts["l_shoulder"][0] + pts["r_shoulder"][0]) / 2
        y = 1278 * (pts["l_shoulder"][1] + pts["r_shoulder"][1]) / 2 - 60 + bob
        if self.head_mode == "уезжает":
            y += 0.7 * idx
        elif self.head_mode == "рывок":
            y += 0.0 if idx < NFRAMES // 2 else 40.0
        return {"head": (float(x), float(y)), "why": ""}

    def paths(self):
        return fl.frame_paths(self.dir)


FIXTURE_FPS = 30


def analyse(material, **kw):
    """Прогон прибора на фикстуре: ВСЕ ТРИ точки внедрения подменены."""
    kw.setdefault("fps", FIXTURE_FPS)
    kw.setdefault("gif", False)
    kw.setdefault("head", material.head)
    return fl.find_loops(material.dir, reader=material.reader, gray=material.gray, **kw)


class PoseAxis(unittest.TestCase):
    def test_pose_gap_of_a_frame_against_itself_is_zero(self):
        """Негативный контроль «прибор обязан промолчать»."""
        a = norm(skeleton(0.3))
        self.assertEqual(fl.pose_gap(a, a), 0.0)

    def test_pose_gap_is_a_hand_computable_literal(self):
        """Ожидаемое — литерал, посчитанный на бумаге, а не импорт."""
        a = skeleton(0.0)
        b = dict(a)
        b["l_wrist"] = (a["l_wrist"][0], a["l_wrist"][1] + 0.02, 1.0)
        self.assertAlmostEqual(fl.pose_gap(norm(a), norm(b)), 0.008333, places=6)

    def test_pose_gap_is_the_same_number_as_pose_delta(self):
        """своя реализация обязана давать то же, что приёмка поз проекта."""
        a, b = skeleton(0.0), skeleton(0.3)
        mine = fl.pose_gap(norm(a), norm(b))
        theirs = pose.pose_delta(a, b)["mean"]
        self.assertAlmostEqual(
            mine,
            theirs,
            places=4,
            msg="расхождение с pose.pose_delta означает, что "
            "прибор судит не той величиной, которой "
            "судит вся остальная приёмка поз",
        )

    def test_a_frame_without_hips_is_not_a_pose_at_all(self):
        """Приведение требует оба бедра и оба плеча — иначе позы нет."""
        half = norm(skeleton(0.0, seen=("l_hip", "l_shoulder", "r_shoulder")))
        self.assertIsNone(half)
        self.assertIsNone(fl.pose_gap(half, norm(skeleton(0.0))))

    def test_pose_gap_says_nothing_when_a_frame_has_no_body(self):
        self.assertIsNone(fl.pose_gap(None, norm(skeleton(0.0))))
        self.assertIsNone(fl.pose_gap(norm(skeleton(0.0)), None))


class FlowAxis(unittest.TestCase):
    def _bounce(self):
        """Четыре кадра: поза в 0 и в 2 ОДНА И ТА ЖЕ, движение противоположно."""
        a = skeleton(0.0)
        down = dict(a)
        up = dict(a)
        down["l_wrist"] = (a["l_wrist"][0], a["l_wrist"][1] + 0.02, 1.0)
        up["l_wrist"] = (a["l_wrist"][0], a["l_wrist"][1] - 0.02, 1.0)
        return fl.states([a, down, a, up])

    def test_the_pose_axis_alone_calls_a_bounce_a_perfect_seam(self):
        st = self._bounce()
        self.assertEqual(
            fl.pose_gap(st[0], st[2]),
            0.0,
            "если это перестанет быть нулём, фикстура больше не показывает разбираемый дефект",
        )

    def test_the_flow_axis_catches_it_with_a_hand_computable_literal(self):
        """0.02 кадра при торсе 0.2 — 0.1; направления противоположны, значит"""
        st = self._bounce()
        self.assertAlmostEqual(fl.flow_gap(st, 0, 2), 0.016667, places=6)

    def test_the_flow_axis_is_silent_when_directions_agree(self):
        st = fl.states(loop_sequence(60))
        self.assertAlmostEqual(fl.flow_gap(st, 0, PERIOD), 0.0, places=9)

    def test_the_flow_axis_needs_the_frame_after_the_seam(self):
        st = fl.states(loop_sequence(50))
        self.assertIsNone(
            fl.flow_gap(st, 0, 49),
            "производную в последнем кадре взять не из чего, и это «не смогли», а не ноль",
        )


class Lengths(unittest.TestCase):
    def test_every_length_survives_the_wrapper_snap(self):
        """Прижатие обёртки на кадр разъезжает петлю."""
        for L in fl.admissible_lengths(NFRAMES):
            self.assertEqual(fork_comfy.snap_frames(L), L, f"длина {L} прижмётся")

    def test_the_floor_is_forty_one_frames(self):
        got = fl.admissible_lengths(NFRAMES)
        self.assertEqual(got[0], 41)
        self.assertNotIn(37, got, "37 кадров — 1.23 с, десяток повторов подряд")
        self.assertNotIn(5, got)

    def test_the_ceiling_comes_from_the_product_length_and_not_from_here(self):
        got = fl.admissible_lengths(100000, fps=30)
        self.assertLessEqual(got[-1], fork_comfy.SECONDS_MAX * 30)
        self.assertEqual(got[-1], 297)
        self.assertEqual(
            fl.admissible_lengths(100000, fps=24)[-1],
            237,
            "потолок обязан ехать за частотой источника: 10 с при "
            "24 к/с — это 240 кадров, ближайшее 4k+1 снизу 237",
        )

    def test_without_a_frame_rate_there_is_no_ceiling_at_all(self):
        """Потолок продуктовый и выражен в секундах; без частоты его нет."""
        got = fl.admissible_lengths(1000, fps=None)
        self.assertEqual(got[-1], 997)
        self.assertEqual(got[0], 41)

    def test_a_clip_shorter_than_the_floor_admits_nothing(self):
        self.assertEqual(fl.admissible_lengths(40), [])


class SeamScore(unittest.TestCase):
    def _sim(self):
        return {
            "pose": {(0, 44): 0.02, (10, 54): 0.0},
            "flow": {(0, 44): 0.0, (10, 54): 0.05},
            "lengths": [45],
            "pairs": 2,
            "measured": 2,
            "unmeasurable": 0,
        }

    def test_the_bounce_ranks_worse_than_the_honest_seam(self):
        """При шаге клипа 0.05: A даёт max(0.4, 0) = 0.4, B — max(0, 1.0) = 1.0."""
        got = fl.score_pairs(self._sim(), 0.05)
        self.assertEqual([c["i"] for c in got], [0, 10])
        self.assertEqual([c["score"] for c in got], [0.4, 1.0])

    def test_a_pair_with_one_axis_unmeasured_is_not_a_candidate(self):
        sim = self._sim()
        sim["flow"][(0, 44)] = None
        self.assertEqual([c["i"] for c in fl.score_pairs(sim, 0.05)], [10])

    def test_a_motionless_clip_cannot_be_ranked(self):
        with self.assertRaises(ValueError):
            fl.score_pairs(self._sim(), 0.0)


def cand(i, j, score):
    return {"i": i, "j": j, "frames": j - i + 1, "score": score}


class Suppression(unittest.TestCase):
    def test_overlap_is_a_share_of_the_shorter_loop(self):
        self.assertAlmostEqual(fl.overlap(cand(0, 44, 1), cand(30, 74, 1)), 15 / 45, places=6)
        self.assertEqual(fl.overlap(cand(0, 44, 1), cand(45, 89, 1)), 0.0)

    def test_a_copy_shifted_by_four_frames_is_not_a_second_loop(self):
        got = fl.select([cand(0, 44, 0.5), cand(4, 48, 0.6)])
        self.assertEqual([(c["i"], c["j"]) for c in got["kept"]], [(0, 44)])
        self.assertEqual(got["dropped_overlap"], 1)

    def test_a_third_of_a_loop_in_common_still_counts_as_a_different_loop(self):
        got = fl.select([cand(0, 44, 0.5), cand(30, 74, 0.6)])
        self.assertEqual([(c["i"], c["j"]) for c in got["kept"]], [(0, 44), (30, 74)])

    def test_the_table_is_capped(self):
        many = [cand(k * 50, k * 50 + 44, 0.1 * k) for k in range(8)]
        got = fl.select(many)
        self.assertEqual(len(got["kept"]), 5)


class Repeats(unittest.TestCase):
    def test_the_numbers_match_the_ones_measured_on_the_material(self):
        """Литералы из хэндофа: 45 кадров, склейка N*44+1."""
        got = fl.repeat_plan(45, fps=30)
        self.assertEqual(
            [(r["repeats"], r["frames"], r["seconds"]) for r in got],
            [(4, 177, 5.9), (5, 221, 7.37), (6, 265, 8.83)],
        )

    def test_every_glued_length_survives_the_wrapper_snap(self):
        for L in fl.admissible_lengths(NFRAMES):
            for r in fl.repeat_plan(L):
                self.assertEqual(r["snapped"], r["frames"], f"склейка {r['repeats']}x{L} прижмётся")

    def test_every_admissible_loop_can_be_grown_to_product_length(self):
        """Свойство, а не совпадение: полоса 5-10 с шире вдвое, поэтому"""
        for L in fl.admissible_lengths(NFRAMES, fps=FIXTURE_FPS):
            self.assertTrue(fl.repeat_plan(L, fps=FIXTURE_FPS), f"длину {L} не растянуть в 5-10 с")

    def test_a_loop_longer_than_the_product_fits_nothing(self):
        self.assertEqual(fl.repeat_plan(1000, fps=30), [])


class Gif(unittest.TestCase):
    def test_the_seam_frame_is_not_in_the_gif(self):
        idx = fl.gif_indices(0, 44)
        self.assertIn(0, idx)
        self.assertNotIn(
            44,
            idx,
            "кадр j — повтор кадра i; оставив его, мы показали бы "
            "оператору два одинаковых кадра вместо стыка",
        )

    def test_the_gif_is_thinned(self):
        self.assertEqual(len(fl.gif_indices(0, 44)), 22)
        self.assertEqual(len(fl.gif_indices(0, 300)), 24)
        self.assertLessEqual(len(fl.gif_indices(0, 300)), fl.GIF_MAX_FRAMES)

    def test_a_short_loop_is_not_thinned(self):
        self.assertEqual(fl.gif_indices(10, 22), list(range(10, 22)))

    def test_the_gif_is_written_and_scaled_down(self):
        m = Material(loop_sequence(46), size=(800, 600))
        out = Path(tempfile.mkdtemp(prefix="looper_gif_")) / "loop.gif"
        got = fl.make_gif(m.paths(), 0, 44, out)
        self.assertEqual(got["frames"], 22)
        self.assertEqual(got["size"], (320, 240))
        self.assertGreater(got["bytes"], 0)
        from PIL import Image

        with Image.open(out) as im:
            self.assertEqual(im.n_frames, 22)
            self.assertEqual(im.info["duration"], 60)


class Sequences(unittest.TestCase):
    def test_a_pendulum_has_a_loop_and_it_is_exactly_the_period(self):
        m = Material(loop_sequence())
        got = analyse(m)
        self.assertEqual(got["outcome"], PASS, got["note"])
        best = got["loops"][0]
        self.assertEqual((best["i"], best["j"]), (0, PERIOD))
        self.assertEqual(best["frames"], PERIOD + 1)
        self.assertEqual(best["score"], 0.0)

    def test_a_drift_has_no_loop_and_the_margin_is_1_40(self):
        """ИЗМЕРЕНО: 1.40, и это то число, между которым и 4.2 стоит планка."""
        m = Material(drift_sequence())
        got = analyse(m)
        self.assertEqual(got["outcome"], FAIL, got["note"])
        self.assertEqual(got["loops"], [])
        self.assertAlmostEqual(got["advantage"], 1.4, places=1)
        self.assertIn("ПЕТЕЛЬ НЕ НАШЛОСЬ", got["note"])
        self.assertGreater(
            got["measured_pairs"],
            300,
            "«не нашлось» обязано стоять рядом с числом "
            "разобранных пар, иначе оно неотличимо от «не искали»",
        )

    def test_a_drift_stays_loopless_at_three_different_speeds(self):
        """фикстура берётся с обоих краёв диапазона и из середины."""
        for tire in (0.0005, 0.002, 0.01):
            with self.subTest(tire=tire):
                m = Material(drift_sequence(tire=tire))
                got = analyse(m)
                self.assertEqual(got["outcome"], FAIL)
                self.assertAlmostEqual(got["advantage"], 1.4, places=1)

    def test_a_tiring_pendulum_is_still_a_loop_but_a_worse_one(self):
        """Середина диапазона: повтор есть, но человек по ходу уезжает."""
        m = Material(loop_sequence(tire=0.0005))
        got = analyse(m)
        self.assertEqual(got["outcome"], PASS, got["note"])
        self.assertGreater(
            got["loops"][0]["score"], 0.0, "стык уже не идеален, и это обязано быть видно"
        )

    def test_where_the_bar_bites_is_measured_from_both_sides(self):
        """ИЗМЕРЕНО на одной фикстуре с двумя скоростями сползания:"""
        for tire, outcome, lo, hi in ((0.004, PASS, 3.2, 3.6), (0.006, FAIL, 1.5, 1.8)):
            with self.subTest(tire=tire):
                m = Material([skeleton(t / PERIOD, tired=tire * t) for t in range(NFRAMES)])
                got = analyse(m)
                self.assertEqual(got["outcome"], outcome, got["note"])
                self.assertGreater(got["advantage"], lo)
                self.assertLess(got["advantage"], hi)

    def test_two_exercises_give_two_loops_one_in_each(self):
        m = Material(two_exercises())
        got = analyse(m)
        self.assertEqual(got["outcome"], PASS, got["note"])
        self.assertEqual(
            len(got["loops"]),
            2,
            f"упражнения два, петель {len(got['loops'])}: "
            f"{[(lp['i'], lp['j']) for lp in got['loops']]}",
        )
        halves = sorted((lp["i"] < NFRAMES // 2) for lp in got["loops"])
        self.assertEqual(
            halves, [False, True], "обе петли уехали в одну половину — второе упражнение потеряно"
        )

    def test_a_still_clip_is_not_measurable_rather_than_loopless(self):
        """«не смогли» не сворачивается ни в «годно», ни в «не годно»."""
        m = Material(still_sequence())
        got = analyse(m)
        self.assertEqual(got["outcome"], UNMEASURED, got["note"])
        self.assertEqual(got["loops"], [])

    def test_no_detector_is_not_the_same_as_no_bodies(self):
        m = Material(loop_sequence(), broken=True)
        got = analyse(m)
        self.assertEqual(got["outcome"], UNMEASURED, got["note"])
        self.assertIn("mediapipe", got["note"])

    def test_half_the_frames_without_a_body_is_not_measurable(self):
        m = Material(loop_sequence(), missing=range(0, NFRAMES, 2))
        got = analyse(m)
        self.assertEqual(got["outcome"], UNMEASURED, got["note"])
        self.assertIn("48 из 96", got["note"])

    def test_a_tenth_of_the_frames_without_a_body_still_measures(self):
        m = Material(loop_sequence(), missing=range(0, NFRAMES, 10))
        got = analyse(m)
        self.assertEqual(got["outcome"], PASS, got["note"])
        self.assertEqual(got["taken"], 86)
        self.assertGreater(
            got["unmeasurable_pairs"], 0, "пары с пропавшей позой обязаны считаться отдельно"
        )

    def test_material_shorter_than_a_loop_fails_with_the_number(self):
        m = Material(loop_sequence(20))
        got = analyse(m)
        self.assertEqual(got["outcome"], FAIL, got["note"])
        self.assertIn("20", got["note"])

    def test_a_missing_source_is_not_measurable(self):
        got = fl.find_loops("/no/such/place/at/all", gif=False)
        self.assertEqual(got["outcome"], UNMEASURED)


class ReportAndCache(unittest.TestCase):
    def test_the_report_carries_its_numbers(self):
        """ноль нарушений при нуле проверок — не успех."""
        m = Material(loop_sequence())
        got = analyse(m)
        for key in (
            "frames",
            "taken",
            "pairs",
            "measured_pairs",
            "unmeasurable_pairs",
            "candidates",
            "worthy",
            "dropped_overlap",
            "advantage",
            "typical_step",
        ):
            self.assertIn(key, got, f"в отчёте нет числа {key}")
        self.assertEqual(got["frames"], NFRAMES)
        self.assertEqual(got["pairs"], got["measured_pairs"] + got["unmeasurable_pairs"])

    def test_the_verdict_never_claims_seamlessness(self):
        """Планки бесшовности у модуля нет, и заявлять её он не смеет."""
        m = Material(loop_sequence())
        got = analyse(m)
        self.assertIn("РАНГ, а не вердикт", got["note"])
        self.assertNotIn("бесшов", got["note"].replace("бесшовности", ""))

    def test_three_outcomes_get_three_exit_codes(self):
        self.assertEqual(sorted(fl.EXIT_BY_OUTCOME.values()), [0, 1, 2])
        self.assertEqual(
            fl.EXIT_BY_OUTCOME[UNMEASURED],
            2,
            "сведение «не смогли» в 0 читало бы отсутствие детектора как успех",
        )

    def test_the_table_prints_the_repeat_plan(self):
        m = Material(loop_sequence())
        got = analyse(m)
        txt = fl.table(got)
        self.assertIn("4x=177", txt)
        self.assertIn("5.9", txt)

    def test_the_cache_spares_the_expensive_step(self):
        m = Material(loop_sequence(50))
        cache = Path(tempfile.mkdtemp(prefix="looper_cache_")) / "poses.json"
        first = fl.read_all(m.paths(), reader=m.reader, cache=cache)
        self.assertEqual(len(m.calls), 50)
        second = fl.read_all(m.paths(), reader=m.reader, cache=cache)
        self.assertEqual(len(m.calls), 50, "кэш не сработал: детектор позвали снова")
        self.assertEqual(second["cached"], 50)
        self.assertEqual(first["poses"], second["poses"])

    def test_a_changed_frame_invalidates_its_cache_entry(self):
        """Кэш, переживающий подмену кадра, — второй источник истины."""
        from PIL import Image

        m = Material(loop_sequence(50))
        cache = Path(tempfile.mkdtemp(prefix="looper_cache_")) / "poses.json"
        fl.read_all(m.paths(), reader=m.reader, cache=cache)
        Image.new("RGB", (64, 64), (1, 2, 3)).save(m.dir / "0007.png")
        got = fl.read_all(m.paths(), reader=m.reader, cache=cache)
        self.assertEqual(got["cached"], 49)
        self.assertEqual(len(m.calls), 51)

    def test_a_cache_of_the_current_version_is_honoured(self):
        """Версия закреплена ЛИТЕРАЛОМ: импортировав её из модуля, тест"""
        m = Material(loop_sequence(10))
        cache = Path(tempfile.mkdtemp(prefix="looper_cache_")) / "poses.json"
        fl.read_all(m.paths(), reader=m.reader, cache=cache)
        raw = json.loads(cache.read_text(encoding="utf-8"))
        raw["version"] = 1
        cache.write_text(json.dumps(raw), encoding="utf-8")
        got = fl.read_all(m.paths(), reader=m.reader, cache=cache)
        self.assertEqual(got["cached"], 10)
        self.assertEqual(len(m.calls), 10)

    def test_a_cache_of_another_version_is_ignored(self):
        m = Material(loop_sequence(10))
        cache = Path(tempfile.mkdtemp(prefix="looper_cache_")) / "poses.json"
        cache.write_text(json.dumps({"version": 999, "frames": {"мусор": None}}), encoding="utf-8")
        got = fl.read_all(m.paths(), reader=m.reader, cache=cache)
        self.assertEqual(got["cached"], 0)
        self.assertEqual(len(m.calls), 10)


class Cuts(unittest.TestCase):
    def test_a_cut_is_found(self):
        m = Material(loop_sequence(), cuts=(47,), blank=True)
        got = fl.cuts(m.paths(), gray=m.gray)
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(got["cuts"], [47])
        self.assertEqual(got["steps"], NFRAMES - 1)
        self.assertAlmostEqual(got["worst"], 21.9, places=1)

    def test_a_cut_is_not_invented_on_smooth_material(self):
        """Негативный контроль второй стороны: ровный ход — не рез."""
        m = Material(loop_sequence(), blank=True)
        got = fl.cuts(m.paths(), gray=m.gray)
        self.assertEqual(got["cuts"], [])
        self.assertAlmostEqual(
            got["worst"],
            1.41,
            places=2,
            msg="самый резкий переход ровного маятника — полтора типичных, до планки 4.0 далеко",
        )

    def test_a_shake_is_not_a_cut_either(self):
        """Скачок втрое против типичного — это ещё движение, а не монтаж."""
        import numpy as np

        m = Material(loop_sequence(), blank=True)
        m.gray = lambda path: np.full(
            (8, 8), float(sum(3 if k % 10 == 0 else 1 for k in range(int(Path(path).stem)))) % 200
        )
        got = fl.cuts(m.paths(), gray=m.gray)
        self.assertEqual(got["worst"], 3.0)
        self.assertEqual(
            got["cuts"],
            [],
            "планка стоит выше тряски и ниже монтажа; сдвинув её "
            "вниз, мы объявим резом каждый резкий мах",
        )

    def test_the_default_pixel_reader_downscales_to_the_declared_side(self):
        """Точка внедрения по умолчанию читается настоящим кадром, а не макетом:"""
        m = Material(loop_sequence(2), size=(240, 426))
        arr = fl.read_gray(str(m.paths()[0]))
        self.assertEqual(arr.shape, (fl.CUT_SIDE, fl.CUT_SIDE))
        self.assertEqual(arr.shape, (96, 96))

    def test_a_frozen_clip_cannot_be_asked_about_cuts(self):
        """«резов нет» и «резы не искали» — разные ответы."""
        import numpy as np

        m = Material(loop_sequence(), blank=True)
        got = fl.cuts(m.paths(), gray=lambda p: np.zeros((8, 8)))
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertIn("НЕ ИСКАЛИ", got["note"])

    def test_a_loop_across_a_cut_is_never_offered(self):
        """САМАЯ ОПАСНАЯ ИЗ ПРОВЕРОК."""
        m = Material(loop_sequence(), cuts=(47,), blank=True)
        got = analyse(m)
        self.assertEqual(got["outcome"], PASS, got["note"])
        self.assertEqual(got["cuts"], [47])
        self.assertGreater(got["rejected"].get("рез внутри петли", 0), 0)
        for lp in got["loops"]:
            with self.subTest(loop=(lp["i"], lp["j"])):
                self.assertTrue(lp["j"] <= 47 or lp["i"] > 47, "петля перешагнула монтажный рез")


class Presence(unittest.TestCase):
    def test_several_people_are_not_this_module_to_decide(self):
        """выбор протагониста уже решён в `fork_props`, второго не заводим."""
        m = Material(loop_sequence(), people={k: 2 for k in range(NFRAMES)})
        got = analyse(m)
        self.assertEqual(got["outcome"], UNMEASURED, got["note"])
        self.assertIn("fork_props", got["note"])
        self.assertIn("протагонист", got["note"])
        self.assertEqual(got["crowd"], [2])

    def test_nobody_at_all_is_not_the_same_as_no_loops(self):
        m = Material(loop_sequence(), missing=range(NFRAMES))
        got = analyse(m)
        self.assertEqual(got["outcome"], UNMEASURED, got["note"])
        self.assertEqual(got["taken"], 0)
        self.assertIn("человека в кадре нет", got["note"])

    def test_a_person_leaving_mid_clip_blocks_loops_across_the_gap(self):
        m = Material(loop_sequence(200), missing=range(60, 80))
        got = analyse(m)
        self.assertEqual(got["outcome"], PASS, got["note"])
        self.assertGreater(got["rejected"].get("человека нет в кадре внутри петли", 0), 0)
        for lp in got["loops"]:
            with self.subTest(loop=(lp["i"], lp["j"])):
                self.assertTrue(
                    lp["j"] < 60 or lp["i"] > 79, "петля идёт через участок, где человека нет"
                )

    def test_a_single_blink_of_the_detector_does_not_kill_the_loop(self):
        """Другая сторона того же порога: одиночный промах — не уход из кадра."""
        m = Material(loop_sequence(), missing=range(0, NFRAMES, 10))
        got = analyse(m)
        self.assertEqual(got["outcome"], PASS, got["note"])
        self.assertEqual(got["rejected"], {})

    def test_presence_separates_a_blink_from_a_departure(self):
        poses = loop_sequence(100)
        for k in list(range(20, 40)) + [70]:
            poses[k] = None
        who = fl.presence(poses)
        self.assertEqual(who["gaps"], [(20, 39), (70, 70)])
        self.assertEqual(who["long_gaps"], [(20, 39)])
        self.assertEqual(who["left_at"], 20)


class LongMaterial(unittest.TestCase):
    def test_thinning_lands_on_a_true_period_and_costs_less(self):
        """Что уточнение обещает — и чего оно НЕ обещает."""
        m = Material(loop_sequence(200, tire=0.0002), blank=True)
        full = analyse(m, stride=1)
        thin = analyse(m, stride=5)
        self.assertEqual(full["outcome"], PASS)
        self.assertEqual(thin["outcome"], PASS)
        for name, rep in (("полный", full), ("прорежённый", thin)):
            best = rep["loops"][0]
            with self.subTest(scan=name):
                self.assertEqual(
                    (best["j"] - best["i"]) % PERIOD, 0, f"{name} проход взял не период движения"
                )
        self.assertLess(thin["pose_frames"], full["pose_frames"])
        self.assertLess(
            abs(thin["loops"][0]["score"] - full["loops"][0]["score"])
            / max(full["loops"][0]["score"], 1e-9),
            0.2,
            "тонкая оценка уехала от полной больше чем на пятую часть — "
            "значит единицы измерения разъехались всерьёз",
        )
        self.assertEqual(thin["loops"][0]["coarse"]["i"] % 5, 0)

    def test_thinning_breaks_at_nyquist_and_here_is_where(self):
        """ИЗМЕРЕНО, отрицательный результат с числами."""
        m = Material(loop_sequence(200), blank=True)
        for stride in (5, 10, 20):
            with self.subTest(stride=stride, expect=PASS):
                got = analyse(m, stride=stride)
                self.assertEqual(got["outcome"], PASS)
        for stride in (21, 23, 25):
            with self.subTest(stride=stride, expect=FAIL):
                got = analyse(m, stride=stride)
                self.assertEqual(got["outcome"], FAIL)

    def test_a_short_clip_is_scanned_at_full_rate(self):
        m = Material(loop_sequence(), blank=True)
        got = analyse(m)
        self.assertEqual(got["scan"], fl.SCAN_FULL)
        self.assertEqual(got["stride"], 1)

    def test_a_long_clip_thins_itself_and_says_so(self):
        m = Material(loop_sequence(950), blank=True)
        got = analyse(m)
        self.assertEqual(got["scan"], fl.SCAN_COARSE)
        self.assertEqual(got["stride"], 5)
        self.assertEqual(got["frames"], 950)
        self.assertLess(got["pose_frames"], 950 // 2)
        self.assertGreaterEqual(got["pose_frames"], 190)

    def test_material_past_the_ceiling_is_refused_rather_than_awaited(self):
        m = Material(loop_sequence(), blank=True)
        got = analyse(m, max_frames=50)
        self.assertEqual(got["outcome"], UNMEASURED, got["note"])
        self.assertEqual(got["scan"], fl.SCAN_TOO_LONG)
        self.assertIn("нарежьте", got["note"].lower())
        ok = analyse(m, max_frames=200)
        self.assertEqual(ok["outcome"], PASS)

    def test_the_default_ceiling_is_twenty_minutes(self):
        """Умолчание закреплено литералом: 36000 кадров при 30 к/с."""
        self.assertEqual(fl.MAX_FRAMES, 36000)
        self.assertEqual(fl.MAX_FRAMES / fork_comfy.WRAP_FPS / 60, 20)


def many_exercises(count, *, each=50):
    """РАЗНЫЕ упражнения: разная конфигурация тела, а не разная амплитуда."""
    plans = [
        ("arms", 0.16, 0.0),
        ("legs", 0.20, 0.42),
        ("line", 0.20, -0.40),
        ("arms", 0.05, 0.85),
        ("legs", 0.06, -0.80),
        ("line", 0.09, 1.25),
    ]
    anchor = ("l_hip", "r_hip", "l_shoulder", "r_shoulder")
    out = []
    for e in range(count):
        mode, amp, tilt = plans[e]
        for t in range(each):
            sk = skeleton((e * 7 + t) / PERIOD, mode=mode, amp=amp)
            out.append({k: (x, y if k in anchor else y + tilt, v) for k, (x, y, v) in sk.items()})
    return out


class FiveOnTheOutput(unittest.TestCase):
    def test_five_exercises_give_five_different_loops(self):
        m = Material(many_exercises(5), blank=True)
        got = analyse(m)
        self.assertEqual(got["outcome"], PASS, got["note"])
        self.assertEqual(len(got["loops"]), 5)
        starts = sorted(lp["i"] // 50 for lp in got["loops"])
        self.assertEqual(
            starts,
            [0, 1, 2, 3, 4],
            "пять петель обязаны прийти из пяти разных упражнений, а не пять раз из одного",
        )

    def test_a_sixth_exercise_does_not_make_a_sixth_line(self):
        m = Material(many_exercises(6), blank=True)
        got = analyse(m)
        self.assertEqual(len(got["loops"]), 5)
        self.assertEqual(got["asked"], 5)

    def test_a_pendulum_is_one_movement_and_not_three_cards(self):
        """Маятник — ОДНО упражнение, сколько бы раз он ни повторился."""
        m = Material(loop_sequence(), blank=True)
        got = analyse(m)
        self.assertEqual(len(got["loops"]), 1, got["note"])
        self.assertGreater(got["dropped_duplicate"], 0)
        self.assertIn("РАЗНЫХ ДВИЖЕНИЙ МЕНЬШЕ ЗАКАЗАННЫХ 5", got["note"])
        self.assertIn(
            f"схлопнуто как повтор того же движения {got['dropped_duplicate']}", got["note"]
        )


class PixelAxis(unittest.TestCase):
    def _sim(self, pixel):
        return {
            "pose": {(0, 44): 0.0},
            "flow": {(0, 44): 0.0},
            "pixel": {(0, 44): pixel},
            "joints": {(0, 44): 12},
            "lengths": [45],
            "pairs": 1,
            "measured": 1,
            "unmeasurable": 0,
        }

    def test_a_perfect_pose_with_a_jumped_picture_ranks_badly(self):
        """Поза и направление сошлись идеально, а картинка прыгнула вчетверо"""
        got = fl.score_pairs(self._sim(0.4), 0.05, pix_step=0.1)
        self.assertEqual(got[0]["score"], 4.0)
        self.assertEqual(got[0]["seam_pixel"], 4.0)

    def test_the_pixel_axis_is_silent_when_the_picture_matches(self):
        got = fl.score_pairs(self._sim(0.0), 0.05, pix_step=0.1)
        self.assertEqual(got[0]["score"], 0.0)

    def test_a_pair_without_pixels_is_not_judged_by_two_axes_out_of_three(self):
        got = fl.score_pairs(self._sim(None), 0.05, pix_step=0.1)
        self.assertEqual(
            got,
            [],
            "стык, у которого не измерена одна из трёх осей, — это «не смогли», а не «идеально»",
        )

    def test_without_a_pixel_store_the_instrument_works_on_two_axes(self):
        got = fl.score_pairs(self._sim(None), 0.05)
        self.assertEqual(got[0]["score"], 0.0)
        self.assertIsNone(got[0]["seam_pixel"])

    def test_a_drifting_picture_kills_a_loop_the_pose_calls_perfect(self):
        """СИНТЕТИЧЕСКИЙ ДВОЙНИК НАХОДКИ НА `chain_frames`."""
        import numpy as np

        m = Material(loop_sequence(), blank=True)
        m.gray = lambda path: np.full((8, 8), 2.5 * int(Path(path).stem))
        got = analyse(m)
        self.assertEqual(got["outcome"], FAIL, got["note"])
        self.assertEqual(got["loops"], [])
        blind = analyse(m, pixel_weight=0.0)
        self.assertEqual(blind["outcome"], PASS)
        self.assertEqual(blind["loops"][0]["score"], 0.0)


class SourceFps(unittest.TestCase):
    def test_the_same_frames_at_24_and_30_are_not_the_same_seconds(self):
        """, обе стороны: один и тот же материал при разной частоте обязан"""
        m = Material(loop_sequence(), blank=True)
        at30 = analyse(m, fps=30)
        at24 = analyse(m, fps=24)
        self.assertEqual(at30["fps"], 30)
        self.assertEqual(at24["fps"], 24)
        self.assertEqual(at30["fps_source"], fl.FPS_GIVEN)
        self.assertEqual(at30["loops"][0]["frames"], 45)
        self.assertEqual(at24["loops"][0]["frames"], 45)
        self.assertEqual(at30["loops"][0]["seconds"], 1.5)
        self.assertEqual(at24["loops"][0]["seconds"], 1.88)

    def test_the_repeat_plan_follows_the_source_rate(self):
        """Числа составителя шаблонов: петля 53 кадра при 24 к/с. Пятикратный повтор даёт"""
        self.assertEqual(
            [(r["repeats"], r["frames"], r["seconds"]) for r in fl.repeat_plan(53, fps=24)],
            [(3, 157, 6.54), (4, 209, 8.71)],
        )
        self.assertEqual(
            [(r["repeats"], r["frames"], r["seconds"]) for r in fl.repeat_plan(53, fps=30)],
            [(3, 157, 5.23), (4, 209, 6.97), (5, 261, 8.7)],
        )

    def test_a_directory_alone_has_no_frame_rate_and_says_so(self):
        """Третий исход: не «30 по умолчанию», а «неизвестна»."""
        m = Material(loop_sequence(), blank=True)
        got = fl.find_loops(m.dir, reader=m.reader, gray=m.gray, head=m.head, gif=False)
        self.assertEqual(got["outcome"], PASS, got["note"])
        self.assertIsNone(got["fps"])
        self.assertEqual(got["fps_source"], fl.FPS_UNKNOWN)
        self.assertTrue(got["loops"])
        self.assertIsNone(got["loops"][0]["seconds"])
        self.assertEqual(got["loops"][0]["repeats"], [])
        txt = fl.table(got)
        self.assertIn("частота неизвестна", txt)
        self.assertIn("45", txt, "кадры печатаются всегда: они измерены")
        self.assertIn("неизвестна", [s["note"] for s in got["steps"] if s["step"] == "частота"][0])

    def test_a_video_file_tells_its_own_frame_rate(self):
        m = Material(loop_sequence(), blank=True)
        movie = m.dir.parent / "driving.mp4"
        movie.write_text("не настоящее видео: раскодировщик подменён", encoding="utf-8")
        seen = {}

        def decode(path, out_dir, **kw):
            seen["path"] = path
            return {
                "outcome": PASS,
                "paths": [str(p) for p in m.paths()],
                "fps_in": 24,
                "fps_out": 24,
                "note": "фикстура",
            }

        got = fl.find_loops(
            movie, reader=m.reader, gray=m.gray, head=m.head, gif=False, decode=decode
        )
        self.assertEqual(got["fps"], 24)
        self.assertEqual(got["fps_source"], fl.FPS_PROBED)
        self.assertEqual(got["loops"][0]["seconds"], 1.88)
        self.assertEqual(seen["path"], str(movie))

    def test_a_hand_given_rate_wins_over_the_file(self):
        """Частота, названная человеком, не перебивается файлом молча."""
        m = Material(loop_sequence(), blank=True)
        movie = m.dir.parent / "driving2.mp4"
        movie.write_text("фикстура", encoding="utf-8")

        def decode(path, out_dir, **kw):
            return {
                "outcome": PASS,
                "paths": [str(p) for p in m.paths()],
                "fps_in": 24,
                "fps_out": 24,
                "note": "фикстура",
            }

        got = fl.find_loops(
            movie, reader=m.reader, gray=m.gray, head=m.head, gif=False, decode=decode, fps=30
        )
        self.assertEqual(got["fps"], 30)
        self.assertEqual(got["fps_source"], fl.FPS_GIVEN)


class JointCoverage(unittest.TestCase):
    def test_the_loop_reports_how_many_joints_were_compared(self):
        """На драйвинге правое запястье видно на 46 кадрах из 96, и стык лучшей"""
        blind = (
            "l_hip",
            "r_hip",
            "l_shoulder",
            "r_shoulder",
            "l_knee",
            "r_knee",
            "l_ankle",
            "r_ankle",
            "l_elbow",
            "r_elbow",
        )
        m = Material([skeleton(t / PERIOD, seen=blind) for t in range(NFRAMES)], blank=True)
        got = analyse(m)
        self.assertEqual(got["outcome"], PASS, got["note"])
        self.assertEqual(got["loops"][0]["joints"], 10)
        txt = fl.table(got)
        self.assertIn("суст", txt)
        self.assertIn("сколько суставов из 12", txt)

    def test_a_fully_visible_body_reports_all_twelve(self):
        m = Material(loop_sequence(), blank=True)
        got = analyse(m)
        self.assertEqual(got["loops"][0]["joints"], 12)
        self.assertNotIn(
            "сколько суставов из 12",
            fl.table(got),
            "пояснение печатается только когда есть что пояснять",
        )


def two_places_one_movement(each=120):
    """Упражнение A, потом B, потом СНОВА A — как в боевом ролике."""
    out = []
    for mode, amp, tilt in (("arms", 0.10, 0.0), ("legs", 0.20, 0.6), ("arms", 0.10, 0.0)):
        for t in range(each):
            out.append(seated(skeleton(t / PERIOD, mode=mode, amp=amp), tilt))
    return out


def same_start_different_moves(each=120):
    """Два упражнения, начинающиеся из ОДНОЙ позы и расходящиеся дальше."""
    return [skeleton(t / PERIOD, mode="line", amp=0.05) for t in range(each)] + [
        skeleton(t / PERIOD, mode="line", amp=0.30) for t in range(each)
    ]


class TwoSieves(unittest.TestCase):
    def test_the_signature_samples_the_loop_at_a_fixed_rate(self):
        """Литералы: петля 0..44 описывается каждым пятым кадром."""
        asked = []

        def state_at(frame):
            asked.append(frame)
            return norm(skeleton(frame / PERIOD))

        sig = fl.loop_signature(state_at, 0, 44)
        self.assertEqual(asked, [0, 5, 10, 15, 20, 25, 30, 35, 40])
        self.assertEqual(len(sig), 9)
        asked.clear()
        fl.loop_signature(state_at, 0, 88)
        self.assertEqual(len(asked), 18)

    def test_the_signature_refuses_when_a_pose_is_missing(self):
        """сверять движения по половине подписи нельзя."""
        self.assertIsNone(fl.loop_signature(lambda f: None, 0, 44))
        self.assertIsNone(
            fl.loop_signature(lambda f: None if f == 15 else norm(skeleton(0.0)), 0, 44)
        )

    def test_the_signature_gap_ignores_where_the_cycle_starts(self):
        """То же упражнение с другой точки цикла — то же упражнение."""
        at = lambda f: norm(skeleton(f / PERIOD))
        a = fl.loop_signature(at, 0, 44)
        b = fl.loop_signature(at, 11, 55)
        self.assertLess(fl.signature_gap(a, b), 0.1)
        other = fl.loop_signature(
            lambda f: norm(skeleton(f / PERIOD, mode="legs", amp=0.14)), 0, 44
        )
        self.assertGreater(fl.signature_gap(a, other), 0.3)

    def test_the_vectorised_gap_equals_pose_gap(self):
        """быстрая арифметика обязана давать то же, чем судит вся приёмка."""
        at = lambda f: norm(skeleton(f / PERIOD))
        a = [at(0), at(7)]
        b = [at(3), at(19)]
        by_hand = max(
            max(min(fl.pose_gap(x, y) for y in b) for x in a),
            max(min(fl.pose_gap(x, y) for x in a) for y in b),
        )
        self.assertAlmostEqual(fl.signature_gap(a, b), by_hand, places=5)

    def test_the_gap_is_the_worst_phase_not_the_average(self):
        """Совпадения в одной точке цикла недостаточно: берётся худшая фаза."""
        at = lambda f: norm(skeleton(f / PERIOD))
        a = fl.loop_signature(at, 0, 44)
        b = list(a)
        b[3] = norm(skeleton(0.37, mode="legs", amp=0.25))
        gap = fl.signature_gap(a, b)
        self.assertGreater(gap, 0.2, "одна разошедшаяся фаза обязана решать")

    def test_one_movement_in_two_places_collapses(self):
        """ГЛАВНЫЙ СЛУЧАЙ. Кадры не пересекаются, движение одно."""
        m = Material(two_places_one_movement(), blank=True)
        got = analyse(m)
        self.assertEqual(got["outcome"], PASS, got["note"])
        self.assertEqual(
            len(got["loops"]),
            2,
            f"движений два, петель {len(got['loops'])}: "
            f"{[(lp['i'], lp['j']) for lp in got['loops']]}",
        )
        self.assertGreater(got["dropped_duplicate"], 0)

    def test_two_movements_that_start_alike_are_told_apart(self):
        """Сверка ТОЛЬКО ПО НАЧАЛУ схлопнула бы их: стартовые позы совпадают"""
        seq = same_start_different_moves()
        self.assertEqual(seq[0], seq[120], "фикстура сломана: стартовые позы обязаны совпадать")
        st = fl.states(seq)
        at = lambda f: st[f] if 0 <= f < len(st) else None
        typical = fl.typical_step(st)["step"]
        self.assertEqual(
            fl.pose_gap(st[0], st[120]), 0.0, "по началу движения неразличимы — в этом и дело"
        )
        gap = fl.signature_gap(fl.loop_signature(at, 0, 44), fl.loop_signature(at, 120, 164))
        self.assertGreater(
            gap / typical,
            fl.DUPLICATE_MAX_STEPS,
            f"по всей петле обязаны различаться: {gap / typical:.1f} "
            f"типичных шага против порога {fl.DUPLICATE_MAX_STEPS}",
        )

    def test_the_same_movement_with_a_smaller_swing_is_still_one_movement(self):
        """Один и тот же мах с размахом 0.05 и 0.12 — одно упражнение."""
        seq = [skeleton(t / PERIOD, mode="line", amp=0.05) for t in range(120)] + [
            skeleton(t / PERIOD, mode="line", amp=0.12) for t in range(120)
        ]
        st = fl.states(seq)
        at = lambda f: st[f] if 0 <= f < len(st) else None
        gap = (
            fl.signature_gap(fl.loop_signature(at, 0, 44), fl.loop_signature(at, 120, 164))
            / fl.typical_step(st)["step"]
        )
        self.assertGreater(gap, 6.0, "фикстура должна быть ВЫШЕ нижней мутации")
        self.assertLess(gap, fl.DUPLICATE_MAX_STEPS)
        got = analyse(Material(seq, blank=True))
        self.assertEqual(
            len(got["loops"]),
            1,
            f"это одно движение, петель {len(got['loops'])}: "
            f"{[(lp['i'], lp['j']) for lp in got['loops']]}",
        )

    def test_the_two_sieves_catch_different_things(self):
        """Каждое сито обязано ловить своё, и это видно по счётчикам."""
        shifted = Material(loop_sequence(), blank=True)
        one_move = Material(two_places_one_movement(), blank=True)
        a = analyse(shifted)
        b = analyse(one_move)
        self.assertGreater(
            a["dropped_overlap"], 0, "сдвиги на кадр внутри одного места ловит сито диапазонов"
        )
        self.assertGreater(
            b["dropped_duplicate"],
            0,
            "повтор упражнения в другом месте клипа ловит только сито содержания",
        )

    def test_comparing_movements_asks_the_detector_nothing(self):
        """и сверка идёт по УЖЕ СНЯТЫМ позам, новых опросов нет."""
        m = Material(two_places_one_movement(), blank=True)
        analyse(m)
        self.assertEqual(
            len(m.calls),
            360,
            "детектор позы обязан быть вызван ровно по разу на "
            "кадр: сверка движений своих опросов не делает",
        )


class HeadAxis(unittest.TestCase):
    def test_a_head_that_returns_keeps_the_loop(self):
        m = Material(loop_sequence(), blank=True)
        got = analyse(m)
        self.assertEqual(got["outcome"], PASS, got["note"])
        self.assertEqual(got["loops"][0]["head_state"], PASS)
        self.assertEqual(got["dropped_head"], 0)
        self.assertLess(got["loops"][0]["seam_head"], 1.0)

    def test_a_head_that_never_returns_drops_the_loop(self):
        """, другая сторона: голова уезжает — петля не выпускается."""
        m = Material(loop_sequence(), blank=True, head_mode="уезжает")
        got = analyse(m)
        self.assertGreater(got["dropped_head"], 0, got["note"])
        self.assertEqual(got["loops"], [], got["note"])
        self.assertEqual(got["head_tried"], fl.HEAD_MAX_TRIES)
        self.assertIn(
            "БЮДЖЕТ ГОЛОВЫ ИСЧЕРПАН",
            [s["note"] for s in got["steps"] if s["step"] == "финалисты"][0],
        )

    def test_a_head_jump_is_caught_where_the_pose_is_perfect(self):
        """Поза и картинка идеальны, голова прыгает — этого не видит ничто,"""
        m = Material(loop_sequence(), blank=True, head_mode="рывок")
        got = analyse(m)
        for lp in got["loops"]:
            with self.subTest(loop=(lp["i"], lp["j"])):
                self.assertFalse(
                    lp["i"] < NFRAMES // 2 <= lp["j"] and lp["head_state"] == PASS,
                    "петля перешагнула рывок головы",
                )

    def test_no_head_detector_marks_the_loop_instead_of_failing_it(self):
        """«не смогли посмотреть» не значит «плохо» — но и не молчит."""
        m = Material(loop_sequence(), blank=True, head_broken=True)
        got = analyse(m)
        self.assertEqual(got["outcome"], PASS, got["note"])
        self.assertTrue(got["loops"])
        self.assertEqual(got["loops"][0]["head_state"], UNMEASURED)
        self.assertIn("DWPose", got["loops"][0]["head_note"])
        self.assertIn("ГОЛОВА НЕ ПРОВЕРЕНА", fl.table(got))
        self.assertIsNone(got["head_step"])

    def test_a_face_not_seen_marks_the_loop_too_but_differently(self):
        m = Material(loop_sequence(), blank=True, head_blind=range(0, 60))
        got = analyse(m)
        self.assertTrue(got["loops"])
        self.assertEqual(got["loops"][0]["head_state"], UNMEASURED)
        self.assertIn("лица не видно", got["loops"][0]["head_note"])

    def test_a_head_that_almost_returns_is_kept_and_not_crushed(self):
        """Вес оси головы — 1.0, а не «побольше, чтобы наверняка»."""
        import numpy as np

        m = Material(loop_sequence(), blank=True)
        m.head = lambda path: {
            "head": (
                360.0,
                500.0
                + 6.0 * float(np.sin(2 * np.pi * (int(Path(path).stem) % PERIOD) / PERIOD))
                + 0.01 * int(Path(path).stem),
            ),
            "why": "",
        }
        got = analyse(m)
        self.assertEqual(got["outcome"], PASS, got["note"])
        self.assertEqual(got["dropped_head"], 0, got["note"])
        self.assertGreater(got["loops"][0]["seam_head"], 0.4)
        self.assertLess(got["loops"][0]["seam_head"], 1.5)

    def test_the_head_is_asked_only_about_finalists(self):
        """0.436 с/кадр — голова спрашивается о единицах, а не о тысячах."""
        m = Material(two_places_one_movement(), blank=True)
        got = analyse(m)
        self.assertLessEqual(got["head_tried"], fl.HEAD_MAX_TRIES)
        self.assertLess(got["head_frames"], 120)
        self.assertGreater(got["head_frames"], 0)

    def test_the_scale_of_the_head_axis_is_measured_on_the_clip(self):
        m = Material(loop_sequence(), blank=True)
        got = fl.head_scale(m.paths(), reader=m.head)
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(got["measured"], 40)
        self.assertEqual(got["frames"], 80)

    def test_the_scale_says_when_it_cannot_be_measured(self):
        m = Material(loop_sequence(), blank=True, head_broken=True)
        got = fl.head_scale(m.paths(), reader=m.head)
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertIsNone(got["step"])
        self.assertIn("спросить нечем", got["reason"])


class NoHeavyImports(unittest.TestCase):
    def test_importing_the_module_does_not_pull_mediapipe(self):
        """обеспечивается устройством модуля, а не договорённостью."""
        import subprocess
        import sys

        out = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import lipsync.fork_looper as m; print('mediapipe' in sys.modules)",
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        self.assertEqual(out.stdout.strip(), "False", out.stderr[-400:])


def priced(i, j, frames, floor, seam, outcome):
    """Петля с уже посчитанной ценой моста — ВХОД для `rank_loops`."""
    return {
        "i": i,
        "j": j,
        "frames": j - i + 1,
        "bridge": {
            "outcome": outcome,
            "frames": frames,
            "floor": floor,
            "seam": seam,
            "worst_axis": "голова",
            "unmeasured": [] if outcome == PASS else ["голова"],
            "measured": ["тело"],
            "reason": "",
        },
    }


class BridgePrice(unittest.TestCase):
    """Стык, переведённый в кадры подгонки, и три исхода у этого перевода."""

    def test_the_seam_becomes_frames_by_rounding_up(self):
        """«Стык 3.48 типичных шага» — это «не хватает 3.5 кадров обычного"""
        self.assertEqual(fl.bridge_frames(3.48), 4)
        self.assertEqual(fl.bridge_frames(3.01), 4)
        self.assertEqual(fl.bridge_frames(0.01), 1)

    def test_a_seam_that_is_a_whole_number_does_not_get_a_spare_frame(self):
        """Негативный контроль округления с другой стороны: вверх — это"""
        self.assertEqual(fl.bridge_frames(3.0), 3)
        self.assertEqual(fl.bridge_frames(0.0), 0)

    def test_an_unmeasured_seam_has_no_price_and_that_is_not_zero(self):
        """ФОРМА ГЛАВНОГО ДЕФЕКТА: «не смогли», ведущее себя как ноль."""
        self.assertIsNone(fl.bridge_frames(None))

    def test_four_measured_axes_give_a_price_and_name_the_worst(self):
        got = fl.bridge_cost({"поза": 0.99, "поток": 0.91, "пиксели": 1.45, "голова": 3.28})
        self.assertEqual(got["outcome"], "годно")
        self.assertEqual(got["frames"], 4)
        self.assertEqual(got["worst_axis"], "голова")
        self.assertEqual(got["unmeasured"], [])

    def test_a_missing_axis_is_a_third_outcome_and_gives_a_bound(self):
        """«не смогли» не сворачивается ни в «годно», ни в «не годно»."""
        got = fl.bridge_cost({"поза": 1.479, "поток": 2.141, "пиксели": 1.935, "голова": None})
        self.assertEqual(got["outcome"], "не смогли проверить")
        self.assertIsNone(got["frames"], "цены у неизмеренного стыка нет")
        self.assertEqual(got["floor"], 3, "но нижняя граница есть, и она в кадрах")
        self.assertEqual(got["unmeasured"], ["голова"])

    def test_the_same_loop_with_the_head_measured_gets_a_real_price(self):
        """Негативный контроль с другой стороны: та же петля, у которой"""
        got = fl.bridge_cost(
            {"поза": 1.479, "поток": 2.141, "пиксели": 1.935, "голова": 11.74}, max_frames=99
        )
        self.assertEqual(got["outcome"], "годно")
        self.assertEqual(got["frames"], 12)

    def test_nothing_measured_at_all_has_no_bound_either(self):
        got = fl.bridge_cost({"поза": None, "голова": None})
        self.assertEqual(got["outcome"], "не смогли проверить")
        self.assertIsNone(got["frames"])
        self.assertIsNone(got["floor"], "границу тоже не из чего вывести")

    def test_a_long_bridge_is_a_no_and_not_a_dearer_yes(self):
        """Третий исход у моста: слишком длинный — это «эту петлю не берём»."""
        got = fl.bridge_cost({"тело": 3.0, "голова": 12.4}, max_frames=8)
        self.assertEqual(got["outcome"], "не годно")
        self.assertEqual(got["frames"], 13)
        self.assertIn("12.40", got["reason"])

    def test_a_lower_bound_over_the_ceiling_is_already_a_no(self):
        """«Не смогли» не выкупает длинный мост."""
        got = fl.bridge_cost({"тело": 9.5, "голова": None}, max_frames=8)
        self.assertEqual(got["outcome"], "не годно")
        self.assertEqual(got["floor"], 10)
        self.assertIsNone(got["frames"], "посчитанной ценой это не стало")

    def test_the_ceiling_shipped_is_eight_frames(self):
        """Б2: отгружаемое значение сторожит тест НА САМО ЗНАЧЕНИЕ, литералом."""
        self.assertEqual(fl.BRIDGE_MAX_FRAMES, 8)

    def test_the_ceiling_decides_at_exactly_eight_frames(self):
        """с обеих сторон: мост ровно в потолок — годно, на кадр длиннее —"""
        self.assertEqual(fl.bridge_cost({"тело": 8.0})["outcome"], "годно")
        self.assertEqual(fl.bridge_cost({"тело": 8.01})["outcome"], "не годно")


class TwoQueues(unittest.TestCase):
    """Неизмеренная ось не имеет права удешевлять кандидата."""

    def test_an_unmeasured_candidate_never_ranks_above_a_measured_one(self):
        """ГЛАВНАЯ ПРАВКА, в чистом виде."""
        got = fl.rank_loops(
            [priced(200, 244, None, 0, 0.0, UNMEASURED), priced(100, 144, 4, 4, 3.28, PASS)]
        )
        self.assertEqual([(lp["i"], lp["j"]) for lp in got], [(100, 144), (200, 244)])

    def test_inside_the_measured_queue_the_cheaper_bridge_wins(self):
        """Негативный контроль с другой стороны: когда измерены все,"""
        got = fl.rank_loops(
            [
                priced(10, 54, 9, 9, 8.1, PASS),
                priced(20, 64, 2, 2, 1.4, PASS),
                priced(30, 74, 5, 5, 4.6, PASS),
            ]
        )
        self.assertEqual([lp["bridge"]["frames"] for lp in got], [2, 5, 9])

    def test_unmeasured_candidates_are_ordered_among_themselves_by_the_bound(self):
        """Вторая очередь — тоже очередь, а не свалка."""
        got = fl.rank_loops(
            [priced(10, 54, None, 6, 5.2, UNMEASURED), priced(20, 64, None, 2, 1.1, UNMEASURED)]
        )
        self.assertEqual([lp["i"] for lp in got], [20, 10])

    def test_a_blind_face_no_longer_takes_the_first_place(self):
        """То же самое, но целиком через прибор."""
        seq = two_exercises_second_is_perfect()
        seen = analyse(Material(seq, blank=True))
        self.assertEqual(
            [(lp["i"], lp["j"]) for lp in seen["loops"]], [(48, 92), (0, 44)], seen["note"]
        )
        self.assertEqual([lp["bridge"]["frames"] for lp in seen["loops"]], [0, 1])

        blind = analyse(Material(seq, blank=True, head_blind=range(48, NFRAMES)))
        self.assertEqual(
            [(lp["i"], lp["j"]) for lp in blind["loops"]], [(0, 44), (48, 92)], blind["note"]
        )
        last = blind["loops"][1]
        self.assertEqual(last["head_state"], UNMEASURED)
        self.assertIsNone(last["bridge"]["frames"])
        self.assertEqual(
            last["bridge"]["floor"], 0, "нижняя граница у него ДЕШЕВЛЕ, и всё равно он второй"
        )
        self.assertEqual(blind["loops"][0]["bridge"]["frames"], 1)

    def test_the_deferred_candidate_suppresses_nobody(self):
        """Отложенный не занимает места и не подавляет соседей по кадрам."""
        seq = two_exercises_second_is_perfect()
        blind = analyse(Material(seq, blank=True, head_blind={48}))
        first = blind["loops"][0]
        self.assertEqual(
            first["head_state"], PASS, "первым обязан идти измеренный, а не отложенный"
        )
        self.assertEqual(
            (first["i"], first["j"]),
            (49, 93),
            "сосед отложенного на кадр вправо — лицо на нём видно",
        )

    def test_the_table_marks_a_bound_so_it_cannot_be_read_as_a_price(self):
        """(в) — пометка без изменения порядка — это то, что подвело."""
        blind = analyse(
            Material(two_exercises_second_is_perfect(), blank=True, head_blind=range(0, 48))
        )
        txt = fl.table(blind)
        bound = [r for r in txt.splitlines() if r.strip().startswith("2 ")][0]
        self.assertIn("≥1к", bound, txt)
        self.assertIn("≤", bound, txt)
        self.assertIn("мост", txt.splitlines()[0])

    def test_the_counters_say_how_many_bridges_were_priced_and_how_many_not(self):
        """ноль отвергнутых при нуле посчитанных мостов — не успех."""
        blind = analyse(
            Material(two_exercises_second_is_perfect(), blank=True, head_blind=range(48, NFRAMES))
        )
        self.assertEqual(blind["bridge_measured"], 1)
        self.assertEqual(blind["head_unchecked"], 1)
        self.assertEqual(blind["dropped_bridge"], 0)
        note = [s["note"] for s in blind["steps"] if s["step"] == "финалисты"][0]
        self.assertIn("МОСТЫ: посчитано 1", note)
        self.assertIn("не смогли посчитать 1", note)

    def test_the_bridge_is_measured_by_the_local_step_not_the_clip_median(self):
        """Длина моста — величина АБСОЛЮТНАЯ, и знаменатель у неё локальный."""
        got = analyse(Material(two_speeds(), blank=True))
        loop = got["loops"][0]
        self.assertEqual(loop["bridge"]["frames"], 2)
        self.assertEqual(loop["bridge_seams"]["поза"], 1.028)
        self.assertEqual(loop["seam_pose"], 0.123, "тот же стык по клиповой медиане")
        self.assertEqual(
            math.ceil(max(loop["seam_pose"], loop["seam_flow"])),
            1,
            "по клиповой медиане мост вышел бы вдвое короче",
        )

    def test_the_head_axis_too_is_divided_by_its_own_local_step(self):
        """У КАЖДОЙ ОСИ ЗНАМЕНАТЕЛЬ СВОЙ, и у головы он идёт в другую сторону."""
        m = Material(two_exercises_second_is_perfect(), blank=True)
        m.head = lambda path: {
            "head": (
                360.0,
                500.0
                + (1.0 if int(Path(path).stem) < NFRAMES // 2 else 24.0)
                * math.sin(2 * math.pi * (int(Path(path).stem) % PERIOD) / PERIOD)
                + 0.05 * int(Path(path).stem),
            ),
            "why": "",
        }
        got = analyse(m)
        loop = got["loops"][0]
        self.assertEqual((loop["i"], loop["j"]), (48, 92), got["note"])
        self.assertEqual(loop["seam_head"], 0.852, "локальный шаг головы")
        self.assertEqual(loop["seam_head_clip"], 11.381, "клиповый шаг головы")
        self.assertEqual(
            loop["bridge"]["frames"], 1, "по клиповому мосту вышло бы 12 кадров и отказ"
        )

    def test_the_local_head_scale_is_asked_of_eight_pairs(self):
        """Б2: у отгружаемого значения свой тест, литералом и отдельно."""
        self.assertEqual(fl.HEAD_LOCAL_PAIRS, 8)
        m = Material(loop_sequence(), blank=True)
        got = fl.head_scale(m.paths()[0:45], reader=m.head, pairs=8)
        self.assertEqual(got["measured"], 8)
        self.assertEqual(got["frames"], 16)

    def test_a_bridge_priced_without_the_pixel_axis_says_so(self):
        """та же форма дефекта, найденная грепом по модулю, — но здесь она"""
        got = analyse(Material(loop_sequence(), blank=True))
        self.assertTrue(got["loops"][0]["pixel_axis_off"])
        self.assertIn("пиксельная ось клипа НЕ ИЗМЕРЕНА", fl.table(got))

    def test_the_pixel_note_is_silent_on_a_clip_where_that_axis_worked(self):
        """Негативный контроль ЧЕРЕЗ ПРИБОР: пометка обязана молчать."""
        import numpy as np

        m = Material(loop_sequence(), blank=True)
        m.gray = lambda path: np.full(
            (8, 8),
            120.0 + 30.0 * math.sin(2 * math.pi * (int(Path(path).stem) % PERIOD) / PERIOD),
            dtype="float64",
        )
        got = analyse(m)
        self.assertGreater(got["pixel_step"], 0.0, "фикстура обязана включить пиксельную ось")
        self.assertFalse(got["loops"][0]["pixel_axis_off"])
        self.assertNotIn("пиксельная ось клипа НЕ ИЗМЕРЕНА", fl.table(got))

    def test_the_pixel_note_is_silent_when_that_axis_worked(self):
        """Негативный контроль: сторож обязан молчать на входе, где всё"""
        quiet = {
            "fps": 30,
            "dropped_bridge": 0,
            "loops": [
                {
                    "rank": 1,
                    "i": 0,
                    "j": 44,
                    "frames": 45,
                    "seconds": 1.5,
                    "joints": 12,
                    "score": 0.5,
                    "seam_pose": 0.5,
                    "seam_flow": 0.2,
                    "seam_pixel": 0.4,
                    "seam_head": 0.3,
                    "advantage": 3.0,
                    "repeats": [],
                    "gif": None,
                    "head_state": PASS,
                    "pixel_axis_off": False,
                    "bridge": {
                        "outcome": PASS,
                        "frames": 1,
                        "floor": 1,
                        "seam": 0.5,
                        "unmeasured": [],
                    },
                }
            ],
        }
        txt = fl.table(quiet)
        self.assertNotIn("пиксельная ось", txt)
        self.assertNotIn("ЦЕНА МОСТА НЕ ПОСЧИТАНА", txt)
        self.assertIn("1к", txt)

    def test_a_head_that_never_returns_is_dropped_by_the_bridge_now(self):
        """Отбраковка по голове осталась, но её выносит ЦЕНА МОСТА, а не"""
        got = analyse(Material(loop_sequence(), blank=True, head_mode="уезжает"))
        self.assertEqual(got["loops"], [], got["note"])
        self.assertGreater(got["dropped_bridge"], 0)
        self.assertEqual(
            got["dropped_bridge"], got["dropped_head"], "длинными эти мосты сделала именно голова"
        )


if __name__ == "__main__":
    unittest.main()
