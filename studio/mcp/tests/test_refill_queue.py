"""Очередь дочитывания: порядок, знаменатели и третий исход.

Сеть и диск сюда не заходят — все три источника подаются данными (Т4).
"""

from __future__ import annotations

import importlib.util
import unittest
from datetime import date
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "refill_queue",
    Path(__file__).resolve().parents[3] / "scripts" / "refill_queue.py",
)
assert SPEC and SPEC.loader
refill = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refill)


def work(reason: str, model: str) -> dict:
    return {"reason": reason, "model": model, "detail": "", "where": ""}


class Order(unittest.TestCase):
    def test_a_stale_vendor_claim_outranks_a_question_we_could_not_answer(self):
        """Неверный ответ дороже отсутствующего: им мы отвечаем прямо сейчас."""
        rows = refill.order(
            [work("спросили — не знаем", "a"), work("протухший вендорский факт", "b")]
        )
        self.assertEqual([r["model"] for r in rows], ["b", "a"])

    def test_proven_demand_outranks_future_demand(self):
        rows = refill.order([work("новое семейство", "a"), work("спросили — не знаем", "b")])
        self.assertEqual([r["model"] for r in rows], ["b", "a"])

    def test_a_new_family_outranks_a_new_version(self):
        rows = refill.order(
            [work("новая версия известного семейства", "a"), work("новое семейство", "b")]
        )
        self.assertEqual([r["model"] for r in rows], ["b", "a"])

    def test_an_unknown_reason_goes_last_and_does_not_crash(self):
        """Очередь, падающая от новой строки, перестаёт быть очередью."""
        rows = refill.order([work("причина, которой ещё нет", "a"), work("новое семейство", "b")])
        self.assertEqual([r["model"] for r in rows], ["b", "a"])

    def test_inside_one_reason_the_order_is_stable_by_name(self):
        rows = refill.order([work("новое семейство", "z"), work("новое семейство", "a")])
        self.assertEqual([r["model"] for r in rows], ["a", "z"])


class ReasonsAreOneString(unittest.TestCase):
    """Е1: причина живёт в одном месте, и производители берут её оттуда.

    Тесты порядка подают в `order()` литералы, набранные в тесте, — то есть
    проверяют копию. Эти проверяют СВЯЗЬ: что реально порождают производители
    и знает ли об этом таблица приоритетов.
    """

    def test_every_reason_a_producer_emits_has_a_priority(self):
        payload = {
            "new_families": [{"family": "x", "uploaders": ["a", "b"], "examples": []}],
            "new_versions": [{"stem": "y", "family": "x", "count": 2, "examples": []}],
        }
        produced = {r["reason"] for r in refill.discovered_work(payload)}
        produced |= {refill.STALE_VENDOR, refill.STALE_OTHER, refill.ASKED_UNKNOWN}
        unranked = produced - set(refill.PRIORITY)
        self.assertEqual(unranked, set())

    def test_the_lowest_rung_is_ranked_below_the_others(self):
        """Пятая ступень тоже константа-решение: в живой очереди это 26 строк
        из 34, и без сторожа её можно было поставить впереди вендорской."""
        rows = refill.order([work(refill.STALE_OTHER, "a"), work(refill.STALE_VENDOR, "b")])
        self.assertEqual([r["model"] for r in rows], ["b", "a"])

    def test_the_lowest_rung_still_outranks_a_reason_nobody_ranked(self):
        """Нижняя ступень — не то же самое, что «причина, которой нет в таблице».

        Абсолютное значение ступени ничего не решает, решает порядок, поэтому
        подмена 5 на 6 или 7 не может ничего покрасить и теста на неё не будет.
        А вот 99 — может: там сидит корзина неизвестных причин, и совпасть с
        ней значит потерять различие между «низкий приоритет» и «не разобрано».
        """
        rows = refill.order([work("причина, которой ещё нет", "a"), work(refill.STALE_OTHER, "b")])
        self.assertEqual([r["model"] for r in rows], ["b", "a"])

    def test_the_lowest_rung_is_below_future_demand_too(self):
        rows = refill.order([work(refill.STALE_OTHER, "a"), work(refill.NEW_VERSION, "b")])
        self.assertEqual([r["model"] for r in rows], ["b", "a"])


class Verdict(unittest.TestCase):
    def test_all_sources_silent_is_the_third_outcome(self):
        """Р1: нечего читать и нечем мерить — разные вещи."""
        code = refill.report([], {"a": False, "b": False}, 5)
        self.assertEqual(code, 2)

    def test_one_silent_source_is_still_could_not_measure(self):
        code = refill.report([work("новое семейство", "a")], {"a": True, "b": False}, 5)
        self.assertEqual(code, 2)

    def test_all_sources_answered_with_an_empty_queue_is_a_pass(self):
        """Пустая очередь при трёх живых источниках — это хорошая новость."""
        code = refill.report([], {"a": True, "b": True}, 5)
        self.assertEqual(code, 0)


class Sources(unittest.TestCase):
    def test_a_fact_younger_than_the_threshold_is_not_work(self):
        rows = refill.stale_work(today=date(2026, 1, 1), path=Path("нет такого файла"))
        self.assertEqual(rows, [])

    def test_a_discovery_run_that_never_happened_yields_no_rows(self):
        self.assertEqual(refill.discovered_work(None), [])

    def test_a_discovered_family_and_version_land_with_their_own_reasons(self):
        payload = {
            "new_families": [
                {"family": "sensenova", "uploaders": ["a", "b"], "task": "any", "examples": ["a/x"]}
            ],
            "new_versions": [
                {"stem": "minimax h3", "family": "minimax", "count": 42, "examples": ["b/y"]}
            ],
        }
        rows = refill.discovered_work(payload)
        self.assertEqual(
            [r["reason"] for r in rows],
            ["новое семейство", "новая версия известного семейства"],
        )


if __name__ == "__main__":
    unittest.main()
