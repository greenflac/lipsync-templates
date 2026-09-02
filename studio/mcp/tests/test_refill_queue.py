"""Очередь дочитывания: порядок, знаменатели и третий исход.

Сеть и диск сюда не заходят — все три источника подаются данными (Т4).
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from studio.mcp import advice

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
        """Все ТРИ производителя вызываются по-настоящему.

        Первая редакция этого теста подставляла константы руками для двух из
        трёх — то есть сравнивала `PRIORITY` сам с собой, и опечатка на стороне
        `stale_work`/`missed_work` оставляла её зелёной (найдено независимой
        проверкой 2026-08-31). Это ровно тот дефект, который тест закрывает.
        """
        payload = {
            "new_families": [{"family": "x", "uploaders": ["a", "b"], "examples": []}],
            "new_versions": [{"stem": "y", "family": "x", "count": 2, "examples": []}],
        }
        produced = {r["reason"] for r in refill.discovered_work(payload)}

        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "misses.jsonl"
            row = '{"model":"h3-max","attribute":"","outcome":"could not measure",'
            row += '"known":0,"asked_on":"2026-08-31"}\n'
            journal.write_text(row * 2, encoding="utf-8")
            produced |= {r["reason"] for r in refill.missed_work(journal)}

            facts = Path(tmp) / "facts.jsonl"
            facts.write_text(
                "\n".join(
                    [
                        '{"model":"m","attribute":"a","value":"v","source_url":'
                        '"https://example.test/x","tier":"vendor","stated_on":"2020-01-01"}',
                        '{"model":"m","attribute":"b","value":"v","source_url":'
                        '"https://example.test/y","tier":"blog","stated_on":"2020-01-01"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            produced |= {r["reason"] for r in refill.stale_work(path=facts)}

        self.assertEqual(len(produced), 5)  # все пять ступеней действительно порождаются
        self.assertEqual(produced - set(refill.PRIORITY), set())

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


class Gate(unittest.TestCase):
    """`check_journal` — функция, производящая коды возврата для scripts/check.

    Сторож стоял на её помощнике, а не на ней: подмена `if broken or torn` на
    `if broken` оставляла все тесты зелёными и возвращала исходный дефект
    целиком (найдено независимой проверкой 2026-08-31). Тот же класс, который
    этими же тестами и чинили.
    """

    def journal(self, body: str) -> int:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "misses.jsonl"
            path.write_text(body, encoding="utf-8")
            return refill.check_journal(path)

    GOOD = '{"model":"a","outcome":"pass","known":1,"asked_on":"2026-08-31"}\n'

    def test_a_whole_journal_passes(self):
        self.assertEqual(self.journal(self.GOOD), 0)

    def test_a_torn_line_fails_the_build(self):
        self.assertEqual(self.journal(self.GOOD + "обрыв{"), 1)

    def test_a_line_broken_by_schema_fails_the_build(self):
        bad = '{"model":"a","outcome":"годно","known":1,"asked_on":"2026-08-31"}\n'
        self.assertEqual(self.journal(self.GOOD + bad), 1)

    def test_a_non_numeric_known_fails_instead_of_crashing(self):
        bad = '{"model":"a","outcome":"pass","known":"много","asked_on":"2026-08-31"}\n'
        self.assertEqual(self.journal(bad), 1)

    def test_an_empty_journal_is_the_third_outcome_not_a_pass(self):
        self.assertEqual(self.journal("// только шапка\n"), 2)

    def test_a_journal_of_pure_junk_is_broken_not_empty(self):
        """Второй исход не подменяется третьим: строки БЫЛИ, они испорчены."""
        self.assertEqual(self.journal("это не json\nи это тоже\n"), 1)


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


class ОпубликованноеВОчередьНеИдёт(unittest.TestCase):
    """Правило одно на проект, и жило оно в двух местах (Е1).

    `advice.stale` научили отличать дату публикации от износа 2026-09-02, а
    здесь тот же расчёт был переписан заново — и починка сюда не доехала.
    ИЗМЕРЕНО в тот же день: в очереди из 51 строки лежало 10 ссылок на arXiv,
    старейшей 1352 дня.
    """

    def _база(self, rows: list[dict]) -> Path:
        файл = Path(tempfile.mkdtemp()) / "facts.jsonl"
        файл.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
        )
        return файл

    СТАРАЯ_СТАТЬЯ = {
        "model": "м",
        "attribute": "failure_mode",
        "value": "статья",
        "source_url": "https://arxiv.org/abs/2212.10562",
        "tier": "paper",
        "stated_on": "2022-12-20",
    }
    СТАРАЯ_ЦЕНА = {
        "model": "м",
        "attribute": "price_per_second_usd",
        "value": "0.06",
        "source_url": "https://fal.ai/models/x",
        "tier": "portal",
        "stated_on": "2024-01-01",
    }

    def test_статья_в_очередь_не_попадает(self):
        очередь = refill.stale_work(path=self._база([self.СТАРАЯ_СТАТЬЯ]))
        self.assertEqual(очередь, [])

    def test_цена_площадки_в_очередь_попадает(self):
        """Вторая половина (И5): иначе правило просто выключает очередь."""
        очередь = refill.stale_work(path=self._база([self.СТАРАЯ_ЦЕНА]))
        self.assertEqual([r["model"] for r in очередь], ["м"])

    def test_правило_берётся_из_одного_места(self):
        """Т2 наоборот, и нарочно: здесь ожидаемое — ИМЕННО импорт, потому что
        проверяется, что второго списка тиров не завели."""
        self.assertIs(refill.advice.PUBLISHED_TIERS, advice.PUBLISHED_TIERS)
