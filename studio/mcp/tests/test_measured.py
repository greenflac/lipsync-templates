"""Адрес для измеренных чисел: можно ли его покраснеть, и молчит ли он, когда надо.

Все фикстуры — литералы (Т2), ни одна не читает файл с диска: развилки вынесены
из точек входа именно затем, чтобы тест до них дотягивался (Т5).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio import measured

_SPEC = importlib.util.spec_from_file_location(
    "check_measured", Path(__file__).resolve().parents[3] / "scripts" / "check_measured.py"
)
assert _SPEC and _SPEC.loader
gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)


def _good(**over: object) -> dict:
    row = {
        "id": "m-0000000001",
        "subject": "что-то измеримое",
        "origin": "ИЗМЕРЕНО",
        "outcome": "годно",
        "measured_on": "2026-08-31",
        "note": "зачем это число",
        "script": "scripts/что-то.py",
    }
    row.update(over)  # type: ignore[arg-type]
    return row


class ANumberNobodyCanRecheckIsARumour(unittest.TestCase):
    def test_a_record_with_neither_script_nor_method_is_refused(self) -> None:
        row = _good()
        del row["script"]
        assert [p.field for p in measured.problems(row)] == ["script/method"]

    def test_a_method_alone_is_enough(self) -> None:
        """Негативный контроль: не всякое число рождается скриптом. Замер curl-ом
        — тоже замер, и требовать файл значило бы гнать его в прозу."""
        row = _good()
        del row["script"]
        row["method"] = "curl -sL -o /dev/null -w %{size_download}"
        assert measured.problems(row) == []

    def test_a_complete_record_has_no_problems(self) -> None:
        assert measured.problems(_good()) == []


class OriginAndOutcomeAreClosedSets(unittest.TestCase):
    def test_an_origin_outside_I4_is_refused(self) -> None:
        """«ВЫБРАНО», поданное как «ИЗМЕРЕНО», потом никто не решается тронуть —
        ради этого поле и закрыто списком."""
        assert [p.field for p in measured.problems(_good(origin="намерено"))] == ["origin"]

    def test_all_three_origins_are_admitted(self) -> None:
        """Другая сторона: список обязан пропускать всё, что в нём есть."""
        for origin in ("ИЗМЕРЕНО", "РАСЧЁТ"):
            assert measured.problems(_good(origin=origin)) == [], origin

    def test_CHOSEN_without_a_method_is_refused(self) -> None:
        """У выбранного числа обязан быть автор и основание, иначе оно
        неотличимо от взятого с потолка."""
        row = _good(origin="ВЫБРАНО")
        assert [p.field for p in measured.problems(row)] == ["method"]
        row["method"] = "владелец, 2026-08-31, из двух вариантов в чате"
        assert measured.problems(row) == []

    def test_an_outcome_outside_R1_is_refused(self) -> None:
        assert [p.field for p in measured.problems(_good(outcome="ok"))] == ["outcome"]

    def test_a_NEGATIVE_result_is_a_first_class_record(self) -> None:
        """И6: серия неудач — это измеренная граница. Если бы «не годно»
        отвергалось, отрицательные результаты снова уехали бы в прозу."""
        assert measured.problems(_good(outcome="не годно")) == []
        assert measured.problems(_good(outcome="не смогли")) == []


class TheStoreIsALogNotATable(unittest.TestCase):
    def test_a_superseded_record_drops_out_of_current(self) -> None:
        rows = [
            _good(id="m-старое", value=0.30),
            _good(id="m-новое", value=0.2571, supersedes="m-старое"),
        ]
        assert [r["id"] for r in measured.current(rows)] == ["m-новое"]

    def test_the_superseded_record_is_still_IN_THE_FILE(self) -> None:
        """Негативный контроль: исправленное число не затирается, иначе тот, кто
        процитировал старое, не узнает, что с ним стало."""
        rows = [_good(id="m-старое"), _good(id="m-новое", supersedes="m-старое")]
        assert len(rows) == 2
        assert any(r["id"] == "m-старое" for r in rows)

    def test_nothing_is_dropped_when_nothing_supersedes(self) -> None:
        rows = [_good(id="m-1"), _good(id="m-2")]
        assert len(measured.current(rows)) == 2


class FindingThreeRecordsInsteadOfFortyThousandTokens(unittest.TestCase):
    def test_a_term_matches_subject_note_and_script(self) -> None:
        rows = [
            _good(id="m-1", subject="Civitai: размер листинга"),
            _good(id="m-2", subject="что-то ещё", note="про civitai между делом"),
            _good(id="m-3", subject="третье", script="scripts/probe_civitai_video.py"),
            _good(id="m-4", subject="ничего общего", note="совсем", script="scripts/x.py"),
        ]
        assert [r["id"] for r in measured.find(rows, "civitai")] == ["m-1", "m-2", "m-3"]

    def test_an_empty_term_returns_everything_rather_than_nothing(self) -> None:
        """Пустой запрос — это «покажи всё», а не «ничего не нашлось»."""
        rows = [_good(id="m-1"), _good(id="m-2")]
        assert len(measured.find(rows, "  ")) == 2


class TheHandoffMustNotBecomeTheArchiveAgain(unittest.TestCase):
    def test_a_handoff_over_the_budget_is_caught(self) -> None:
        """Ровно то, что случилось: 2330 строк при потолке 400."""
        out = gate.check_handoffs({"HANDOFF_ветка.md": 2330}, limit=400)
        assert out["outcome"] == FAIL, out["note"]
        assert out["раздулись"] == ["HANDOFF_ветка.md: 2330 строк при потолке 400"]

    def test_a_handoff_within_the_budget_is_NOT_caught(self) -> None:
        """Негативный контроль (И5): гейт, который краснеет всегда, снимут."""
        out = gate.check_handoffs({"HANDOFF_ветка.md": 95}, limit=400)
        assert out["outcome"] == PASS, out["note"]
        assert out["раздулись"] == []

    def test_the_budget_is_a_threshold_and_not_a_wall(self) -> None:
        """Обе стороны константы: ровно потолок проходит, на строку больше — нет."""
        assert gate.check_handoffs({"H.md": 400}, limit=400)["outcome"] == PASS
        assert gate.check_handoffs({"H.md": 401}, limit=400)["outcome"] == FAIL

    def test_the_DEFAULT_budget_is_the_one_the_gate_actually_applies(self) -> None:
        """Раньше каждый тест здесь передавал потолок сам, и подмена константы
        в модуле не красила ни одного из них — то есть сторожа у неё не было.
        Литералы, а не импорт проверяемого значения (Т2)."""
        assert gate.check_handoffs({"H.md": 400})["outcome"] == PASS
        assert gate.check_handoffs({"H.md": 401})["outcome"] == FAIL

    def test_a_grandfathered_handoff_is_counted_apart_not_ignored(self) -> None:
        """Чужой append-only документ не переписывается (Ц2). Но «не считается»
        и «не видно» — разные вещи: он уходит в «не смогли», а не в тишину."""
        out = gate.check_handoffs({gate.GRANDFATHERED[0]: 9999}, limit=400)
        assert out["outcome"] == UNMEASURED
        assert out["violations"] == 0
        assert out["unmeasured"] == 1

    def test_no_handoffs_at_all_is_could_not_measure(self) -> None:
        assert gate.check_handoffs({})["outcome"] == UNMEASURED


class AnEmptyStoreIsNotAPass(unittest.TestCase):
    def test_zero_records_returns_could_not_measure(self) -> None:
        """Р2: ноль нарушений при нуле проверок — не успех."""
        out = gate.check_records([])
        assert out["outcome"] == UNMEASURED
        assert out["checked"] == 0

    def test_records_with_problems_go_red_and_name_them(self) -> None:
        bad = _good()
        del bad["script"]
        out = gate.check_records([_good(), bad])
        assert out["outcome"] == FAIL
        assert out["violations"] == 1
        assert "script/method" in out["проблемы"][0]


if __name__ == "__main__":
    unittest.main()
