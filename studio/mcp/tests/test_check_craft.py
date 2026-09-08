"""Гейт полосы знания: сторожит ли что-нибудь его собственную константу.

ЗАЧЕМ ЭТОТ ФАЙЛ. Разбор 2026-08-31: `scripts/check_craft.py` был шагом гейта
БЕЗ ЕДИНОГО ТЕСТА. Подмена `VERBATIM_MAX_WORDS` на 3 и на 100 не красила ни
одного теста во всех сюитах — то есть у порога, который решает, дословная это
цитата или пересказ, сторожа не было вовсе.

Фикстуры пишутся здесь литералами (Т2) во временный каталог: настоящий корпус
знания в гейте есть, а в CI его может не быть, и тест, которому он нужен,
зеленеет тут и краснеет там.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

_SPEC = importlib.util.spec_from_file_location(
    "check_craft", Path(__file__).resolve().parents[3] / "scripts" / "check_craft.py"
)
assert _SPEC and _SPEC.loader
craft = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(craft)

#: Ровно пятнадцать слов — граница, объявленная константой.
FIFTEEN = (
    "один два три четыре пять шесть семь восемь девять десять "
    "одиннадцать двенадцать тринадцать четырнадцать пятнадцать"
)
SIXTEEN = FIFTEEN + " шестнадцать"


def _record(**over: object) -> dict:
    row: dict[str, object] = {
        "title": "запись",
        "question": "вопрос",
        "claim": "утверждение",
        "mechanism": "механизм",
        "knob": "ручка",
        "evidence": [
            {
                "url": "https://platform.openai.com/docs/x",
                "tier": "vendor",
                "token_seen": "короткая",
            }
        ],
    }
    row.update(over)
    return row


def _audit(rows: list[dict]) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "craft_test.jsonl"
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
        )
        return craft.audit(Path(tmp))


class TheVerbatimCeilingHasBothSides(unittest.TestCase):
    def test_sixteen_words_in_verbatim_is_a_violation(self) -> None:
        out = _audit([_record(verbatim=[SIXTEEN])])
        assert out["outcome"] == FAIL, out["note"]
        assert out["violations"] == 1

    def test_fifteen_words_in_verbatim_is_allowed(self) -> None:
        """Другая сторона константы. Порог, который режет всё, — это не порог,
        а запрет, и он снял бы полкорпуса вместе с законными цитатами."""
        out = _audit([_record(verbatim=[FIFTEEN])])
        assert out["outcome"] == PASS, out["note"]
        assert out["violations"] == 0

    def test_the_SAME_ceiling_applies_to_evidence_token_seen(self) -> None:
        """Вторая дверь. Без этого теста близнец остался бы без сторожа: у
        записи два места, где может лежать чужой текст, и проверять надо оба."""
        out = _audit(
            [
                _record(
                    evidence=[
                        {
                            "url": "https://platform.openai.com/docs/x",
                            "tier": "vendor",
                            "token_seen": SIXTEEN,
                        }
                    ]
                )
            ]
        )
        assert out["outcome"] == FAIL, out["note"]
        assert out["violations"] == 1

    def test_fifteen_words_in_token_seen_is_allowed(self) -> None:
        out = _audit(
            [
                _record(
                    evidence=[
                        {
                            "url": "https://platform.openai.com/docs/x",
                            "tier": "vendor",
                            "token_seen": FIFTEEN,
                        }
                    ]
                )
            ]
        )
        assert out["outcome"] == PASS, out["note"]


class BothDoorsAreFound(unittest.TestCase):
    def test_fragments_reads_verbatim_and_token_seen(self) -> None:
        got = craft._fragments(
            {"verbatim": ["раз"], "evidence": [{"token_seen": "два"}, {"url": "https://x/"}]}
        )
        assert got == [("verbatim", "раз"), ("evidence.token_seen", "два")]

    def test_a_record_with_neither_yields_nothing(self) -> None:
        """Негативный контроль: сборщик, который всегда что-то возвращает,
        нашёл бы цитату там, где её нет."""
        assert craft._fragments({"title": "запись"}) == []


class AnEmptyDirectoryIsNotAPass(unittest.TestCase):
    def test_no_files_at_all_is_could_not_measure(self) -> None:
        """Р2: ноль нарушений при нуле проверок — не успех."""
        with tempfile.TemporaryDirectory() as tmp:
            out = craft.audit(Path(tmp))
            assert out["outcome"] == UNMEASURED, out["note"]
            assert out["checked"] == 0
            assert "not the same as nothing being wrong" in out["note"]


if __name__ == "__main__":
    unittest.main()
