"""Журнал заданных вопросов: считает ли он то, ради чего заведён.

Ожидаемые значения здесь — ЛИТЕРАЛЫ, а не импорт из проверяемого модуля
(правило Т2): импортированное ожидание уедет вместе с кодом и промолчит.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from studio.mcp import misses


def row(
    model: str,
    outcome: str,
    attribute: str = "max_seconds",
    asked_on: str = "2026-08-31",
    known: int | None = None,
):
    """Строка журнала. `known` — сколько атрибутов база реально нашла.

    По умолчанию согласовано с исходом: ответить, ничего не зная, нельзя. Но
    рассогласовать их можно явно — на этом держатся два теста про Е2.
    """
    if known is None:
        known = 0 if outcome == "could not measure" else 1
    return {
        "model": model,
        "attribute": attribute,
        "outcome": outcome,
        "asked_on": asked_on,
        "known": known,
    }


class CoverageCounts(unittest.TestCase):
    def test_no_questions_is_the_third_outcome_not_a_clean_sheet(self):
        """Р2: ноль вопросов — «не смогли», а не покрытие 100%."""
        got = misses.coverage([])
        self.assertEqual(got.outcome, "could not measure")
        self.assertIsNone(got.rate)
        self.assertEqual(got.asked, 0)

    def test_rate_is_answered_over_asked(self):
        got = misses.coverage(
            [
                row("kling-2.6", "pass"),
                row("veo-3.1", "pass"),
                row("h3-max", "could not measure"),
            ]
        )
        self.assertEqual(got.asked, 3)
        self.assertEqual(got.answered, 2)
        self.assertEqual(got.missed, 1)
        self.assertAlmostEqual(got.rate, 2 / 3)
        self.assertEqual(got.outcome, "fail")

    def test_the_evidence_beats_the_flag(self):
        """Е2: `advise` сказал «не смогли» по реестру, а факты о модели есть.

        Поймано на живом прогоне 2026-08-31: `wan-2.2` отсутствует в реестре
        доступности и при этом имеет записанные атрибуты. Считать это промахом
        значит мерить полноту реестра и называть результат покрытием базы.
        """
        got = misses.coverage([row("wan-2.2", "could not measure", known=3)])
        self.assertEqual(got.missed, 0)
        self.assertEqual(got.rate, 1.0)

    def test_a_model_the_base_knows_nothing_about_never_reaches_the_queue_by_flag(self):
        """И обратно: исход `pass` при пустой базе промахом быть не перестаёт."""
        rows = [row("выдумка", "pass", known=0), row("выдумка", "pass", known=0)]
        self.assertEqual([r["model"] for r in misses.queue(rows)], ["выдумка"])

    def test_contested_counts_as_known_not_as_a_miss(self):
        """Спорящие источники — это знание о модели, а не пробел в базе."""
        got = misses.coverage([row("kling-2.6", "fail")])
        self.assertEqual(got.contested, 1)
        self.assertEqual(got.missed, 0)
        self.assertEqual(got.rate, 1.0)

    def test_a_full_sheet_is_pass(self):
        got = misses.coverage([row("kling-2.6", "pass")])
        self.assertEqual(got.outcome, "pass")

    def test_a_malformed_row_leaves_the_denominator(self):
        """Строка без исхода не считается ни попаданием, ни промахом."""
        broken = {"model": "kling", "asked_on": "2026-08-31"}
        got = misses.coverage([row("veo-3.1", "pass"), broken])
        self.assertEqual(got.asked, 1)

    def test_an_unknown_outcome_word_is_refused(self):
        found = misses.problems(row("kling", "годно"))
        self.assertTrue(any("outcome" in p for p in found))


class Queue(unittest.TestCase):
    def test_one_miss_does_not_reach_the_queue(self):
        """Порог: одна опечатка в имени модели не заводит работу."""
        got = misses.queue([row("h3-max", "could not measure")])
        self.assertEqual(got, [])

    def test_two_misses_do(self):
        got = misses.queue([row("h3-max", "could not measure"), row("h3-max", "could not measure")])
        self.assertEqual([r["model"] for r in got], ["h3-max"])
        self.assertEqual(got[0]["misses"], 2)

    def test_answered_models_never_enter_the_queue(self):
        got = misses.queue([row("kling-2.6", "pass"), row("kling-2.6", "pass")])
        self.assertEqual(got, [])

    def test_the_queue_is_ordered_by_how_often_it_was_asked(self):
        rows = [row("h3-max", "could not measure")] * 3 + [
            row("seedance-2", "could not measure")
        ] * 2
        got = misses.queue(rows)
        self.assertEqual([r["model"] for r in got], ["h3-max", "seedance-2"])

    def test_attributes_travel_with_the_queue_row(self):
        rows = [
            row("h3-max", "could not measure", attribute="max_seconds"),
            row("h3-max", "could not measure", attribute="resolution"),
        ]
        got = misses.queue(rows)
        self.assertEqual(got[0]["attributes"], ["max_seconds", "resolution"])


class Writing(unittest.TestCase):
    def test_a_question_lands_as_one_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "misses.jsonl"
            misses.note_question("h3-max", "max_seconds", "could not measure", path=path)
            misses.note_question("kling-2.6", "", "pass", path=path)
            rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual([r["model"] for r in rows], ["h3-max", "kling-2.6"])
        self.assertEqual(rows[0]["outcome"], "could not measure")

    def test_a_malformed_question_is_not_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "misses.jsonl"
            misses.note_question("", "max_seconds", "pass", path=path)
            self.assertFalse(path.exists())

    def test_an_unwritable_log_does_not_break_the_answer(self):
        """Счётчик наблюдает за консультацией, а не участвует в ней."""
        path = Path("/proc/definitely-not-writable/misses.jsonl")
        got = misses.note_question("kling-2.6", "", "pass", path=path)
        self.assertEqual(got["model"], "kling-2.6")

    def test_load_skips_comments_and_junk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "misses.jsonl"
            path.write_text(
                '// шапка\n{"model":"a","outcome":"pass","asked_on":"2026-08-31"}\nне json\n'
            )
            self.assertEqual(len(misses.load(path)), 1)


class Evidence(unittest.TestCase):
    """`known` — число НАЙДЕННОГО, а не число опрошенного."""

    def test_an_attribute_nobody_recorded_is_no_evidence(self):
        """`advise` вернёт checked=2 на выдуманный атрибут знакомой модели."""
        answer = {
            "checked": 2,
            "claims": {"выдуманный": {"checked": 0}},
            "failure_modes": [{"value": "x"}, {"value": "y"}],
            "class_findings": [{"value": "z"}] * 12,
        }
        self.assertEqual(misses.evidence(answer, "выдуманный"), 0)

    def test_class_findings_are_not_about_the_model(self):
        """Одни и те же 12 находок возвращаются для любого имени, включая
        выдуманное: засчитывать их значит закрыть любой вопрос."""
        answer = {"checked": 0, "claims": {}, "failure_modes": [], "class_findings": [1] * 12}
        self.assertEqual(misses.evidence(answer), 0)

    def test_recorded_claims_are_evidence(self):
        answer = {"claims": {"max_seconds": {"checked": 3}}, "failure_modes": [1]}
        self.assertEqual(misses.evidence(answer, "max_seconds"), 3)

    def test_a_whitespace_attribute_is_an_attribute_here_as_it_is_for_advise(self):
        """`advise` решает «атрибут задан» голой истинностью строки.

        Пока здесь стоял `strip`, а там нет, `"   "` для `advise` был атрибутом
        (и не находил ничего), а здесь считался пустым — и вопрос о
        несуществующем свойстве закрывался числом failure_modes модели. Дефект
        возвращался целиком, только через пробел.
        """
        answer = {"claims": {"   ": {"checked": 0}}, "failure_modes": [1, 2]}
        self.assertEqual(misses.evidence(answer, "   "), 0)

    def test_asking_about_the_whole_model_counts_its_failure_modes(self):
        answer = {"claims": {"max_seconds": {"checked": 3}}, "failure_modes": [1, 2]}
        self.assertEqual(misses.evidence(answer, ""), 5)


class TornLines(unittest.TestCase):
    def test_a_line_that_is_not_json_is_counted_not_dropped(self):
        """Журнал пишется open("a"): оборванная строка — его обычная порча."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "misses.jsonl"
            path.write_text(
                '{"model":"a","outcome":"pass","known":1,"asked_on":"2026-08-31"}\nобрыв{'
            )
            rows, torn = misses.read(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(torn, [2])

    def test_a_json_line_that_is_not_an_object_is_torn_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "misses.jsonl"
            path.write_text("[1, 2, 3]\n")
            self.assertEqual(misses.read(path)[1], [1])

    def test_a_known_field_that_is_not_a_number_is_a_schema_problem(self):
        """Раньше это роняло гейт трассировкой вместо третьего исхода."""
        broken = {"model": "a", "outcome": "pass", "asked_on": "2026-08-31", "known": "много"}
        self.assertTrue(any("known" in p for p in misses.problems(broken)))
        self.assertFalse(misses.covered(broken))

    def test_a_boolean_is_not_a_count(self):
        """`True` — это `int` для Python, но не число найденных фактов."""
        broken = {"model": "a", "outcome": "pass", "asked_on": "2026-08-31", "known": True}
        self.assertTrue(any("known" in p for p in misses.problems(broken)))
        self.assertFalse(misses.covered(broken))

    def test_a_negative_known_is_refused(self):
        broken = {"model": "a", "outcome": "pass", "asked_on": "2026-08-31", "known": -1}
        self.assertTrue(any("known" in p for p in misses.problems(broken)))


class Wiring(unittest.TestCase):
    def test_a_whitespace_attribute_is_normalised_once_at_the_entry(self):
        """Оба пути обязаны видеть ОДНУ строку, иначе «атрибут задан»
        решается двумя способами и они расходятся на пробеле.

        Сравниваются два ответа, а не число: числа базы поедут, а равенство
        «спросить про `"   "` — то же, что спросить про модель целиком» —
        это и есть проверяемое утверждение.
        """
        from studio.mcp import server

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "misses.jsonl"
            server.advise_and_note("kling-3.0", "   ", log=path)
            server.advise_and_note("kling-3.0", "", log=path)
            blank, empty = misses.load(path)
        self.assertEqual(blank["attribute"], empty["attribute"])
        self.assertEqual(blank["known"], empty["known"])
        self.assertGreater(empty["known"], 0)

    def test_the_tool_actually_writes_the_question_down(self):
        """Связка, а не копия: без неё модуль честен и не вызывается никем."""
        from studio.mcp import server

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "misses.jsonl"
            server.advise_and_note("совершенно-неизвестная-модель-xyz", "max_seconds", log=path)
            rows = misses.load(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "could not measure")
        self.assertEqual(rows[0]["known"], 0)

    def test_a_known_model_asked_as_a_whole_is_written_as_covered(self):
        """Негативный контроль связки (И5): прибор обязан не только молчать
        на незнакомом, но и шевельнуться на знакомом."""
        from studio.mcp import server

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "misses.jsonl"
            server.advise_and_note("kling-3.0", "", log=path)
            rows = misses.load(path)
        self.assertGreater(rows[0]["known"], 0)


if __name__ == "__main__":
    unittest.main()
