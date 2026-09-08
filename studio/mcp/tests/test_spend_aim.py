"""Деньги на замер: у каждой рекомендуемой модели без применимости есть заявка.

ЗАЧЕМ. Продукт не имеет права рекомендовать модель, про которую нечего сказать
кроме схемы API: применимость — это то, держится ли результат, и она либо
измерена, либо на неё подана заявка. Иначе рекомендация опирается на список
параметров, а список параметров ничего не обещает.

ДВА ДЕФЕКТА, НАЙДЕННЫЕ НЕЗАВИСИМОЙ ПРИЁМКОЙ 2026-09-06 (подменой метки):

1. При нуле моделей без применимости прибор печатал `fail: моделей без
   применимости 0, из них с заявкой 0` — ругань на пустом месте.
2. Третий исход возвращал код 0, то есть «не смогли» было неотличимо от
   «годно» для читающего код возврата (Р2).

Ожидаемое — литералы (Т2), диска и сети нет (Т5).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_spend_aim", Path(__file__).resolve().parents[3] / "scripts" / "check_spend_aim.py"
)
assert _SPEC and _SPEC.loader
прицел = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(прицел)

ЗАЯВКА = [{"model": "kling-3.0"}]


class ИсходПоТрёмЧислам(unittest.TestCase):
    def test_на_каждую_нужную_модель_есть_заявка_это_годно(self):
        self.assertEqual("pass", прицел.решить(["kling-3.0"], ["kling-3.0"], ЗАЯВКА))

    def test_одна_из_двух_без_заявки_это_не_годно(self):
        self.assertEqual("fail", прицел.решить(["kling-3.0", "veo-3.1"], ["kling-3.0"], ЗАЯВКА))

    def test_нечего_сверять_это_третий_исход_а_не_ругань(self):
        """Ноль моделей без применимости — не успех и не провал: утверждение
        «на каждую подана заявка» при нуле моделей пустое."""
        self.assertEqual("could not measure", прицел.решить([], [], ЗАЯВКА))

    def test_ни_одной_заявки_это_тоже_третий_исход(self):
        self.assertEqual("could not measure", прицел.решить(["kling-3.0"], [], []))

    def test_негативный_контроль_исход_не_всегда_третий(self):
        """И5: прибор, всегда отвечающий «не смогли», ничего не сторожит."""
        исходы = {
            прицел.решить(["a"], ["a"], ЗАЯВКА),
            прицел.решить(["a"], [], ЗАЯВКА),
            прицел.решить([], [], ЗАЯВКА),
        }
        self.assertEqual({"pass", "fail", "could not measure"}, исходы)


class КодВозвратаРазличаетТриИсхода(unittest.TestCase):
    """Р1/Р2: третий исход обязан иметь СВОЙ код, иначе он равен успеху."""

    def _с_исходом(self, исход: str) -> int:
        итог = {
            "outcome": исход,
            "checked": 1,
            "violations": 0,
            "unmeasured": 0,
            "рекомендуется": {},
            "без применимости": {},
            "нужны замеры": [],
            "покрыты заявкой": [],
            "заявки мимо": [],
            "заявок": 1,
        }
        import unittest.mock

        with unittest.mock.patch.object(прицел, "свести", lambda: итог):
            return прицел.main(["--check"])

    def test_годно_ноль(self):
        self.assertEqual(0, self._с_исходом("pass"))

    def test_не_годно_один(self):
        self.assertEqual(1, self._с_исходом("fail"))

    def test_не_смогли_два(self):
        self.assertEqual(2, self._с_исходом("could not measure"))


if __name__ == "__main__":
    unittest.main()
