"""Хук «названо, но не спрошено»: обе стороны негативного контроля.

Ожидаемые значения здесь ЛИТЕРАЛЫ, а не импорт из проверяемого модуля (Т2):
импортированное поедет вместе с кодом и промолчит. Сети нет (Т4): всё, что
читается, создаётся во временном каталоге тут же.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from studio import named_not_asked as nna  # noqa: E402

sys.path.insert(0, str(REPO / "scripts"))

import stop_named_not_asked as hook_script  # noqa: E402

#: Имена, которые обязаны быть в базе: на них стоят фикстуры. Литералы (Т2).
NAMES = ["veo-3", "veo-3.1", "sora-2", "kling-3.0", "chatterbox"]


def line(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False) + "\n"


def advice_line(model: str) -> str:
    return line(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "mcp__lipsync-studio__model_advice",
                        "input": {"model": model},
                    }
                ]
            },
        }
    )


def text_line(text: str) -> str:
    return line({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})


class NamesComeFromTheBase(unittest.TestCase):
    def test_the_wildcard_scope_is_not_a_model(self) -> None:
        self.assertNotIn("*", nna.model_names())

    def test_the_base_is_not_a_hand_copied_list(self) -> None:
        names = nna.model_names()
        self.assertIn("kling-3.0", names)
        self.assertGreater(len(names), 100)


class WhatCountsAsNaming(unittest.TestCase):
    def test_a_recommended_name_is_found(self) -> None:
        found = nna.recommended_names("Рекомендую sora-2 на эту задачу.", NAMES)
        self.assertEqual(found, ["sora-2"])

    def test_a_name_without_a_recommendation_is_silent(self) -> None:
        text = "Намерил 24 fps у kling-3.0 против 30 в карточке."
        self.assertEqual(nna.recommended_names(text, NAMES), [])

    def test_a_name_inside_a_code_block_is_silent(self) -> None:
        """Совет ВНУТРИ блока кода — пример, а не совет: строка с подсказкой и
        именем в одной строке, иначе мутация «не вырезать код» выживает."""
        text = (
            'Порядок такой:\n```\n# рекомендую начать с kling-3.0\nmodel_advice("kling-3.0")\n```\n'
        )
        self.assertEqual(nna.recommended_names(text, NAMES), [])

    def test_a_name_quoted_from_the_user_is_silent(self) -> None:
        text = "Вы написали:\n> возьмите kling-3.0\n\nОтвечаю по существу."
        self.assertEqual(nna.recommended_names(text, NAMES), [])

    def test_the_noun_recommendation_is_not_a_recommendation(self) -> None:
        text = "Помечено до попадания в рекомендации: kling-3.0 некоммерческая."
        self.assertEqual(nna.recommended_names(text, NAMES), [])
        english = 'The attribute turns a "works best" recommendation for kling-3.0 into a maximum.'
        self.assertEqual(nna.recommended_names(english, NAMES), [])

    def test_a_version_dot_does_not_cut_the_name_in_half(self) -> None:
        """Прибор врал ровно здесь: `veo-3.1` резалось на `veo-3` и `1`."""
        found = nna.recommended_names("Рекомендую veo-3.1: он держит 8 секунд.", NAMES)
        self.assertEqual(found, ["veo-3.1"])

    def test_a_table_row_keeps_the_name_and_the_verdict_together(self) -> None:
        row = "| **chatterbox** | MIT | самый принятый TTS — для липсинка прямой кандидат |"
        self.assertEqual(nna.recommended_names(row, NAMES), ["chatterbox"])


class ThreeOutcomes(unittest.TestCase):
    def test_all_asked_is_pass_with_counters(self) -> None:
        got = nna.judge("Рекомендую veo-3.1, sora-2 слабее.", ["veo-3.1", "sora-2"], NAMES)
        self.assertEqual(got["outcome"], "pass")
        self.assertEqual((got["checked"], got["violations"], got["unmeasured"]), (2, 0, 0))

    def test_one_of_two_asked_is_fail_on_exactly_the_other(self) -> None:
        got = nna.judge("Рекомендую veo-3.1, sora-2 слабее.", ["veo-3.1"], NAMES)
        self.assertEqual(got["outcome"], "fail")
        self.assertEqual(got["unasked"], ["sora-2"])
        self.assertEqual((got["checked"], got["violations"]), (2, 1))

    def test_an_unreadable_trace_is_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            got = nna.verdict(Path(tmp) / "нет-такого.jsonl")
        self.assertEqual(got["outcome"], "could not measure")
        self.assertEqual((got["checked"], got["violations"], got["unmeasured"]), (0, 0, 1))

    def test_a_trace_without_any_answer_is_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_text(advice_line("sora-2"), encoding="utf-8")
            got = nna.verdict(path)
        self.assertEqual(got["outcome"], "could not measure")
        self.assertEqual(got["unmeasured"], 1)

    def test_no_path_at_all_is_not_pass(self) -> None:
        self.assertEqual(nna.verdict(None)["outcome"], "could not measure")


class ReadingTheTrace(unittest.TestCase):
    def test_asked_names_and_the_last_answer_are_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_text(
                advice_line("VEO-3.1") + text_line("первый") + text_line("последний"),
                encoding="utf-8",
            )
            trace = nna.read_trace(path)
        self.assertEqual(trace["outcome"], "pass")
        self.assertEqual(trace["asked"], ["veo-3.1"])
        self.assertEqual(trace["answer"], "последний")

    def test_a_broken_line_does_not_stop_the_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_text('{"type": "assistant", "text"\n' + text_line("ответ"), encoding="utf-8")
            trace = nna.read_trace(path)
        self.assertEqual(trace["answer"], "ответ")

    def test_the_verdict_reads_a_whole_trace_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_text(
                advice_line("veo-3.1") + text_line("Рекомендую veo-3.1, sora-2 слабее."),
                encoding="utf-8",
            )
            got = nna.verdict(path)
        self.assertEqual(got["outcome"], "fail")
        self.assertEqual(got["unasked"], ["sora-2"])


class ExitCodes(unittest.TestCase):
    """Три исхода — три кода возврата, и третий не сворачивается в первый."""

    def test_clean_answer_lets_the_turn_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_text(text_line("Гейт зелёный, рекомендую посмотреть вывод."), "utf-8")
            code, report = hook_script.hook({"transcript_path": str(path)})
        self.assertEqual(code, 0)
        self.assertIn("нарушений 0", report)

    def test_named_without_asking_blocks_the_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_text(text_line("Рекомендую sora-2."), "utf-8")
            code, report = hook_script.hook({"transcript_path": str(path)})
        self.assertEqual(code, 2)
        self.assertIn("sora-2", report)

    def test_an_unreadable_trace_gets_its_own_code(self) -> None:
        code, report = hook_script.hook({})
        self.assertEqual(code, 3)
        self.assertIn("не смогли 1", report)

    def test_a_second_block_in_a_row_is_not_a_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_text(text_line("Рекомендую sora-2."), "utf-8")
            code, _ = hook_script.hook({"transcript_path": str(path), "stop_hook_active": True})
        self.assertEqual(code, 0)


class ControlSet(unittest.TestCase):
    """И5: вход, где прибор обязан шевельнуться, и входы, где обязан промолчать."""

    def test_every_declared_case_behaves_as_declared(self) -> None:
        cases = hook_script.load_controls()
        outcome = hook_script.run_controls(cases, nna.model_names())
        self.assertEqual(outcome["outcome"], "pass", "\n".join(outcome["lines"]))
        self.assertEqual(outcome["violations"], 0)

    def test_the_set_holds_both_directions(self) -> None:
        cases = hook_script.load_controls()
        expected = {case["expect_outcome"] for case in cases}
        self.assertEqual(expected, {"pass", "fail"})
        self.assertGreaterEqual(len(cases), 9)

    def test_a_one_sided_control_set_is_not_a_green_run(self) -> None:
        """Набор, где прибор ни разу не обязан шевельнуться, ничего не мерит."""
        cases = [c for c in hook_script.load_controls() if c["expect_outcome"] == "pass"]
        outcome = hook_script.run_controls(cases, nna.model_names())
        self.assertEqual(outcome["outcome"], "fail")
        self.assertTrue(any("исход" in line for line in outcome["lines"]))

    def test_an_empty_control_set_is_not_a_green_run(self) -> None:
        outcome = hook_script.run_controls([], nna.model_names())
        self.assertEqual(outcome["outcome"], "could not measure")
        self.assertEqual(outcome["unmeasured"], 1)


if __name__ == "__main__":
    unittest.main()
