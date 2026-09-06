"""Что из каталога площадки считается ценой, а что — числом рядом с ценой.

ЗАЧЕМ. Каталог отдаёт словарь, где рядом с ценами лежат скидки, множители к
тарифу и вложенные объекты переопределений. Ошибка тут стоит денег дважды:
чужое число, принятое за цену, врёт заказчику; настоящая цена, потерянная в
счётчике «не разобрано», делает счётчик шумным — а шумный счётчик перестают
читать, и следующая настоящая пропажа проходит незамеченной.

Величины deepinfra приходят в ЦЕНТАХ и делятся на сто в одном месте:
разъехавшаяся единица — это цена, отличающаяся в СТО раз.

Обе таблицы «это не цены» стояли без охраны: поймано ратчетом R7 2026-09-06.
Ожидаемое — литералы (Т2), сети нет (Т4), вход — словарь, а не запрос (Т5).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "poll_catalogs", Path(__file__).resolve().parents[3] / "scripts" / "poll_catalogs.py"
)
assert _SPEC and _SPEC.loader
опрос = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(опрос)


class ЦентыДелятсяНаСтоВОдномМесте(unittest.TestCase):
    def test_цена_за_токен_переводится_в_доллары(self):
        запись, не_разобрано = опрос.deepinfra_record(
            {"model_name": "m", "pricing": {"cents_per_input_token": 0.008}}, "2026-09-06"
        )
        self.assertEqual(не_разобрано, 0)
        self.assertEqual(
            [{"amount": 8e-05, "unit": "usd_per_token", "condition": "input token"}],
            запись["prices"],
        )

    def test_двоичный_хвост_подрезается(self):
        """`8e-05/100` в двоичной плавающей даёт 8.000000000000001e-07, и такой
        хвост в цене читается как измеренная точность, которой нет."""
        запись, _ = опрос.deepinfra_record(
            {"model_name": "m", "pricing": {"cents_per_sec": 8e-05}}, "2026-09-06"
        )
        self.assertEqual(запись["prices"][0]["amount"], 8e-07)


class ЧужоеЧислоНеСтановитсяЦеной(unittest.TestCase):
    def test_скидка_не_цена_и_не_шум(self):
        """Скидка названа поимённо: она не цена, и в счётчик «не разобрано»
        она тоже не идёт — иначе счётчик зашумится и его перестанут читать."""
        запись, не_разобрано = опрос.deepinfra_record(
            {"model_name": "m", "pricing": {"discount": 0.5}}, "2026-09-06"
        )
        self.assertEqual(запись["prices"], [])
        self.assertEqual(не_разобрано, 0)

    def test_множитель_к_тарифу_не_цена(self):
        """`rate_per_*` — множитель, а не цена; берётся по приставке, потому
        что имён у него много."""
        запись, не_разобрано = опрос.deepinfra_record(
            {"model_name": "m", "pricing": {"rate_per_gpu_hour": 3.2}}, "2026-09-06"
        )
        self.assertEqual(запись["prices"], [])
        self.assertEqual(не_разобрано, 0)

    def test_незнакомое_ненулевое_число_попадает_в_счётчик(self):
        """Негативный контроль (И5): если бы в счётчик не попадало ничего,
        «не разобрано 0» означало бы «мы не смотрели», а не «всё разобрано»."""
        запись, не_разобрано = опрос.deepinfra_record(
            {"model_name": "m", "pricing": {"cents_per_невиданное": 7}}, "2026-09-06"
        )
        self.assertEqual(запись["prices"], [])
        self.assertEqual(не_разобрано, 1)

    def test_ноль_счётчик_не_поднимает(self):
        """Ноль в каталоге означает «этой цены нет», а не «не разобрали»."""
        _, не_разобрано = опрос.deepinfra_record(
            {"model_name": "m", "pricing": {"cents_per_невиданное": 0}}, "2026-09-06"
        )
        self.assertEqual(не_разобрано, 0)

    def test_переопределения_openrouter_не_цена(self):
        """`overrides` — вложенный объект, а не число; в счётчике он был бы
        чистым шумом."""
        запись, не_разобрано = опрос.openrouter_record(
            {"id": "m", "pricing": {"overrides": {"provider": {"prompt": "1"}}}}, "2026-09-06"
        )
        self.assertEqual(запись["prices"], [])
        self.assertEqual(не_разобрано, 0)

    def test_списки_исключений_названы_литералами(self):
        """Т2. Дописать сюда имя — способ убрать настоящую цену из виду, и это
        решение, а не мелочь."""
        self.assertEqual({"overrides"}, set(опрос.OPENROUTER_NOT_PRICES))
        self.assertIn("discount", опрос.DEEPINFRA_NOT_PRICES)
        self.assertNotIn("cents_per_sec", опрос.DEEPINFRA_NOT_PRICES)


if __name__ == "__main__":
    unittest.main()
