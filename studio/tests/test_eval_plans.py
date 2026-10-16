"""The expert-evaluation scorer `scripts/eval_plans.py`, on synthetic answers.

No plan is run here (that is the gate step, ~2 min): each test hands `score()` a
hand-made answer and checks one dimension, with a negative control beside it,
so a scorer that passes everything or fails everything is caught.
"""

from __future__ import annotations

import unittest
from typing import Any

from scripts import eval_plans as E


def answer(steps: list[tuple[str, str]], **k: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "outcome": "could not measure",
        "reason": "план_не_подтверждён",
        "steps": [{"step": s, "chosen": {"model": m}} for s, m in steps],
    }
    d.update(k)
    return d


def row(ref: dict[str, Any]) -> dict[str, Any]:
    return {"id": "t", "class": "c", "brief": "b", "spec": {}, "ref": ref}


class Scorer(unittest.TestCase):
    def test_outcome_mapping(self) -> None:
        self.assertEqual(E.observed_outcome({"reason": "запрещённая_тема", "outcome": "fail"}), "refuse")
        self.assertEqual(E.observed_outcome({"reason": "работа_не_поддерживается"}), "gap")
        self.assertEqual(E.observed_outcome({"reason": "дороже_потолка", "steps": [{}]}), "over_budget")
        self.assertEqual(E.observed_outcome({"reason": "только_монтаж"}), "assembly_only")
        self.assertEqual(E.observed_outcome(answer([("апскейл", "x")])), "plan")
        self.assertEqual(E.observed_outcome(answer([("апскейл", "x")], outcome="fail")), "plan_failed")

    def test_order_and_alternative_paths(self) -> None:
        ref = {"outcome": "plan", "paths": [[{"job": "t2v"}, {"job": "interpolate"}], [{"job": "t2v_audio"}]]}
        ok = E.score(row(ref), answer([("генерация_видео", "a"), ("интерполяция_кадров", "b")]))
        self.assertTrue(ok["correct"], ok)
        ok2 = E.score(row(ref), answer([("видео_со_звуком", "a")]))
        self.assertTrue(ok2["correct"], ok2)
        wrong_order = E.score(row(ref), answer([("интерполяция_кадров", "b"), ("генерация_видео", "a")]))
        self.assertFalse(wrong_order["dims"]["decomposition"]["ok"])
        extra = E.score(row(ref), answer([("генерация_видео", "a"), ("интерполяция_кадров", "b"), ("апскейл", "c")]))
        self.assertIn("extra upscale_video", extra["dims"]["decomposition"]["why"])

    def test_model_sets(self) -> None:
        ref = {"outcome": "plan", "steps": [{"job": "upscale_video", "models": {"any": ["topaz-.*", "seedvr2-(3b|7b)"]}}]}
        self.assertTrue(E.score(row(ref), answer([("апскейл", "seedvr2-7b")]))["correct"])
        bad = E.score(row(ref), answer([("апскейл", "bytedance-upscaler-upscale-video")]))
        self.assertFalse(bad["dims"]["models"]["ok"])
        self.assertTrue(bad["dims"]["decomposition"]["ok"], "a wrong model is not a wrong decomposition")
        excl = {"outcome": "plan", "steps": [{"job": "restore", "models": {"none": [".*deblur.*"]}}]}
        self.assertFalse(E.score(row(excl), answer([("реставрация", "topaz-deblur-video")]))["correct"])
        self.assertTrue(E.score(row(excl), answer([("реставрация", "topaz-denoise-video")]))["correct"])

    def test_shots_cap_is_decomposition_only(self) -> None:
        ref = {"outcome": "plan", "steps": [{"job": "t2i", "shots_max": 1}]}
        d = answer([("генерация_изображения", "m")])
        d["steps"][0]["shots"] = 5
        r = E.score(row(ref), d)
        self.assertFalse(r["dims"]["decomposition"]["ok"])
        self.assertNotIn("models", r["dims"])
        d["steps"][0]["shots"] = 1
        self.assertTrue(E.score(row(ref), d)["correct"])

    def test_price_band(self) -> None:
        ref = {"outcome": "plan", "steps": [{"job": "t2v"}], "price": [1, 5]}
        inside = answer([("генерация_видео", "a")], pipeline_price={"за_ролик": {"usd": 3.0}})
        above = answer([("генерация_видео", "a")], pipeline_price={"за_ролик": {"usd": 48.0}})
        none = answer([("генерация_видео", "a")])
        self.assertTrue(E.score(row(ref), inside)["correct"])
        self.assertFalse(E.score(row(ref), above)["correct"])
        self.assertFalse(E.score(row(ref), none)["correct"], "an unpriced plan does not meet a band")

    def test_notes_read_prose_not_keys_or_echo(self) -> None:
        ref = {"outcome": "plan", "steps": [{"job": "t2v"}], "notes": [{"id": "label", "any": [r"label(l)?ing"]}]}
        keys_only = answer([("генерация_видео", "a")], brief="AI Act labelling please", hosting_labelling=None)
        keys_only["steps"][0]["step_labelling"] = "x"
        self.assertFalse(E.score(row(ref), keys_only)["correct"], "key names and the brief echo must not count")
        said = answer([("генерация_видео", "a")], summary="Add AI Act labelling to the clip.")
        self.assertTrue(E.score(row(ref), said)["correct"])
        quoted = answer([("генерация_видео", "a")])
        quoted["steps"][0]["chosen"]["evidence"] = [{"value": "labelling is optional"}]
        self.assertFalse(E.score(row(ref), quoted)["correct"], "quoted evidence is not the plan speaking")

    def test_baseline_check(self) -> None:
        base = {"total": {"correct": 3}, "classes": {"a": {"correct": 2, "n": 2}, "b": {"correct": 1, "n": 2}}}
        same = {"total": {"correct": 3}, "classes": {"a": {"correct": 2, "n": 2}, "b": {"correct": 1, "n": 2}}}
        trade = {"total": {"correct": 3}, "classes": {"a": {"correct": 1, "n": 2}, "b": {"correct": 2, "n": 2}}}
        self.assertEqual(E.check(same, base), [])
        self.assertTrue(E.check(trade, base), "a class may not pay for another")

    def test_committed_set_is_well_formed(self) -> None:
        rows = E.load_briefs(E.BRIEFS)
        self.assertEqual(E.validate(rows), [])
        self.assertEqual(len(rows), 150)


if __name__ == "__main__":
    unittest.main()
